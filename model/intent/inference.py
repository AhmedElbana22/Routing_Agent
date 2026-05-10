"""
inference.py
Intent parser: raw text -> validated Intent object.

Architecture:
  1. Fine-tuned Qwen2.5-3B-Instruct + LoRA adapter (primary)
     - Adapter loaded from HF Hub (post-training) OR local path (dev)
     - HF_READ_TOKEN used for authentication
  2. JSON extraction + Pydantic validation
  3. Rule-based fallback (never crashes inshallah)
  4. Language detection (always overrides model guess)

Adapter source priority (from config.py):
  "hf"    → load from settings.model.hf_lora_repo
  "local" → load from settings.model.lora_adapter_path
  "none"  → rule-based only
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from model.intent.schema import (
    Constraint,
    Intent,
    Language,
    OptimizationGoal,
    QueryType,
    WeightVector,
)

import structlog

logger = structlog.get_logger(__name__)

 
# System prompt — defined here, not imported from dataset.py
# dataset.py is a training utility and should NOT be a runtime dependency 

SYSTEM_PROMPT = """You are an intent parser for an Alexandria, Egypt public transport assistant.
Extract structured intent from user messages in Arabic or English.

Return ONLY a valid JSON object with these fields:
{
  "query_type": "journey_request" | "followup" | "info_request" | "show_more" | "show_detail" | "unknown" | "clarification_needed",
  "origin": "stop name or null",
  "destination": "stop name or null",
  "optimization": "min_cost" | "min_time" | "min_transfers" | "min_walking" | "balanced" | "same_as_before" | "custom",
  "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
  "constraints": [],
  "language": "ar" | "en" | "mixed",
  "confidence": 0.0-1.0,
  "result_index": null or integer (1-based),
  "info_target": null | "fare" | "schedule" | "line_info",
  "info_params": {}
}

Rules:
- result_index is 1-based: "الأولى"=1, "التانية"=2, "التالتة"=3
- Return null for unknown fields, not empty string
- Do not include any text outside the JSON object
"""

 

# Language detector 


class LanguageDetector:
    """
    Fast rule-based language detection.
    Arabic Unicode range: \u0600-\u06FF
    """

    ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF]")
    LATIN_PATTERN  = re.compile(r"[a-zA-Z]")

    @classmethod
    def detect(cls, text: str) -> Language:
        has_arabic = bool(cls.ARABIC_PATTERN.search(text))
        has_latin  = bool(cls.LATIN_PATTERN.search(text))
        if has_arabic and has_latin:
            return Language.MIXED
        elif has_arabic:
            return Language.ARABIC
        else:
            return Language.ENGLISH

 

# Rule-based fallback parser 


class RuleBasedParser:
    """
    Keyword-based intent extraction.
    Used when model fails or produces invalid JSON.
    Fast: O(n) with compiled regex patterns.
    """

    # Location patterns  
    ORIGIN_PATTERNS_AR = [
        re.compile(r"من\s+([^\s،,؟?]+(?:\s+[^\s،,؟?]+)?)", re.UNICODE),
    ]
    ORIGIN_PATTERNS_EN = [
        re.compile(r"from\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", re.IGNORECASE),
    ]
    DEST_PATTERNS_AR = [
        re.compile(r"(?:لـ|إلى|ل|الى)\s*([^\s،,؟?]+(?:\s+[^\s،,؟?]+)?)", re.UNICODE),
    ]
    DEST_PATTERNS_EN = [
        re.compile(r"to\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", re.IGNORECASE),
    ]

    # Optimization keywords 
    OPT_KEYWORDS: Dict[OptimizationGoal, list] = {
        OptimizationGoal.MIN_TIME: [
            "أسرع", "بسرعة", "أقل وقت", "fastest", "quickest",
            "fast", "quick", "أسرع طريقة", "سريع", "عاجل",
        ],
        OptimizationGoal.MIN_COST: [
            "أرخص", "أقل تمن", "أقل سعر", "cheapest", "cheap",
            "budget", "اقتصادي", "وفر", "أوفر",
        ],
        OptimizationGoal.MIN_TRANSFERS: [
            "أقل تحويلات", "بدون تحويل", "مباشر", "direct",
            "no transfer", "minimum transfers", "مريح",
        ],
        OptimizationGoal.MIN_WALKING: [
            "أقل مشي", "بدون مشي", "minimum walking", "no walking",
        ],
    }

    # Query type keywords 
    FOLLOWUP_KEYWORDS  = ["طب", "وإيه لو", "لو", "what if", "instead", "بدل", "نفس بس"]
    SHOW_MORE_KEYWORDS = ["وريني أكتر", "خيارات تانية", "المزيد", "show more",
                          "more options", "other routes", "أكتر", "تاني"]
    SHOW_DETAIL_KEYWORDS = ["تفاصيل", "وضح", "أكتر عن", "details",
                             "tell me more", "expand", "more about"]
    INFO_KEYWORDS = ["تعريفة", "سعر تذكرة", "مواعيد", "fare", "price",
                     "schedule", "كام بيكلف", "how much", "بكام"]

    # Constraint patterns  
    FARE_CONSTRAINT_AR = re.compile(
        r"مش أكتر من\s+(\d+)\s*جنيه|في حدود\s+(\d+)\s*جنيه|أقل من\s+(\d+)\s*جنيه",
        re.UNICODE,
    )
    FARE_CONSTRAINT_EN = re.compile(
        r"(?:max|maximum|under|within|no more than)\s+(\d+)\s*(?:EGP|egp|pounds?)?",
        re.IGNORECASE,
    )
    DURATION_CONSTRAINT = re.compile(
        r"في\s+(\d+)\s*دقيقة|(?:under|within|max)\s+(\d+)\s*(?:min|minutes?)",
        re.IGNORECASE | re.UNICODE,
    )

    LINE_PATTERN = re.compile(
        r"خط\s+(\w+)|line\s+(\w+)",
        re.IGNORECASE | re.UNICODE,
    )

    def parse(self, text: str) -> Intent:
        """Extract intent using rules. Never raises."""
        try:
            lang         = LanguageDetector.detect(text)
            query_type   = self._detect_query_type(text)
            origin, dest = self._extract_locations(text)
            optimization = self._detect_optimization(text)
            constraints  = self._extract_constraints(text)
            result_index = self._extract_result_index(text)
            info_target, info_params = self._extract_info(text)

            return Intent(
                query_type=query_type,
                origin=origin,
                destination=dest,
                optimization=optimization,
                weights=WeightVector.from_optimization(optimization),
                constraints=constraints,
                language=lang,
                confidence=0.5,    # lower confidence for rule-based
                raw_text=text,
                result_index=result_index,
                info_target=info_target,
                info_params=info_params,
            )
        except Exception as e:
            logger.warning("rule_based_parser_error", error=str(e))
            return Intent(
                query_type=QueryType.UNKNOWN,
                language=LanguageDetector.detect(text),
                confidence=0.1,
                raw_text=text,
            )

    def _detect_query_type(self, text: str) -> QueryType:
        text_lower = text.lower()
        if any(kw in text for kw in self.INFO_KEYWORDS):
            return QueryType.INFO_REQUEST
        if any(kw in text_lower for kw in self.SHOW_MORE_KEYWORDS):
            return QueryType.SHOW_MORE
        if any(kw in text_lower for kw in self.SHOW_DETAIL_KEYWORDS):
            return QueryType.SHOW_DETAIL
        if any(kw in text for kw in self.FOLLOWUP_KEYWORDS):
            return QueryType.FOLLOWUP

        has_origin = (
            bool(re.search(r"من\s+\S+", text, re.UNICODE))
            or bool(re.search(r"from\s+\S+", text, re.IGNORECASE))
        )
        has_dest = (
            bool(re.search(r"(?:لـ|إلى|ل)\s*\S+", text, re.UNICODE))
            or bool(re.search(r"to\s+\S+", text, re.IGNORECASE))
        )
        if has_origin or has_dest:
            return QueryType.JOURNEY_REQUEST

        return QueryType.UNKNOWN

    def _extract_locations(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        origin = None
        destination = None

        for pat in self.ORIGIN_PATTERNS_AR:
            m = pat.search(text)
            if m:
                origin = m.group(1).strip()
                break
        if origin is None:
            for pat in self.ORIGIN_PATTERNS_EN:
                m = pat.search(text)
                if m:
                    origin = m.group(1).strip()
                    break

        for pat in self.DEST_PATTERNS_AR:
            m = pat.search(text)
            if m:
                destination = m.group(1).strip()
                break
        if destination is None:
            for pat in self.DEST_PATTERNS_EN:
                m = pat.search(text)
                if m:
                    destination = m.group(1).strip()
                    break

        # Clean trailing punctuation
        if origin:
            origin = re.sub(r"[،,؟?!.\s]+$", "", origin) or None
        if destination:
            destination = re.sub(r"[،,؟?!.\s]+$", "", destination) or None

        return origin, destination

    def _detect_optimization(self, text: str) -> OptimizationGoal:
        for goal, keywords in self.OPT_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return goal
        return OptimizationGoal.BALANCED

    def _extract_constraints(self, text: str) -> list:
        constraints = []

        m = self.FARE_CONSTRAINT_AR.search(text)
        if m:
            val = next(g for g in m.groups() if g is not None)
            constraints.append(
                Constraint(field="fare", operator="lte", value=float(val))
            )
        elif (m := self.FARE_CONSTRAINT_EN.search(text)):
            constraints.append(
                Constraint(field="fare", operator="lte", value=float(m.group(1)))
            )

        if (m := self.DURATION_CONSTRAINT.search(text)):
            val = next(g for g in m.groups() if g is not None)
            constraints.append(
                Constraint(field="duration", operator="lte", value=float(val))
            )

        return constraints

    def _extract_result_index(self, text: str) -> Optional[int]:
        """
        Extract result index — returns 1-BASED integer.
        agent.py _handle_show_detail does idx-1 to convert to 0-based.
        """
        # 1-based to match agent.py expectation
        mapping = {
            "الأول":  1, "الأولى": 1, "first":  1, "#1": 1, "1": 1, "١": 1,
            "التاني": 2, "التانية": 2, "second": 2, "#2": 2, "2": 2, "٢": 2,
            "التالت": 3, "التالتة": 3, "third":  3, "#3": 3, "3": 3, "٣": 3,
        }
        for key, idx in mapping.items():
            if key in text:
                return idx
        return None

    def _extract_info(self, text: str) -> Tuple[Optional[str], Dict[str, Any]]:
        m = self.LINE_PATTERN.search(text)
        line_id = (m.group(1) or m.group(2)) if m else None
        params  = {"line_id": line_id} if line_id else {}

        if any(kw in text for kw in ["تعريفة", "سعر", "تمن", "fare", "price", "بكام"]):
            return "fare", params
        if any(kw in text for kw in ["مواعيد", "schedule", "hours"]):
            return "schedule", params

        return None, {}

 
# JSON extractor 

class JSONExtractor:
    """
    Robustly extracts JSON object from model output.
    Handles: markdown blocks, wrapped text, truncated JSON.
    """

    JSON_PATTERNS = [
        re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL),
        re.compile(r"```\s*(\{.*?\})\s*```",     re.DOTALL),
        re.compile(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", re.DOTALL),
    ]

    @classmethod
    def extract(cls, text: str) -> Optional[Dict[str, Any]]:
        """Try to extract a JSON object from text. Returns None on failure."""
        for pattern in cls.JSON_PATTERNS:
            match = pattern.search(text)
            if match:
                json_str = match.group(1)
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    fixed = cls._fix_json(json_str)
                    if fixed:
                        return fixed

        # Last resort: entire text
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return None

    @classmethod
    def _fix_json(cls, json_str: str) -> Optional[Dict[str, Any]]:
        """Fix common JSON formatting issues."""
        fixed = re.sub(r",\s*([}\]])", r"\1", json_str)  
        fixed = fixed.replace("'", '"')                   
        fixed = re.sub(r"\bNone\b",  "null",  fixed)
        fixed = re.sub(r"\bTrue\b",  "true",  fixed)
        fixed = re.sub(r"\bFalse\b", "false", fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None

 

# Main Intent Parser 

class IntentParser:
    """
    Primary intent extraction pipeline.

    Flow:
      1. Load model from HF Hub or local (based on adapter_source)
      2. Model generates text → JSON extractor -> Pydantic validation
      3. On any failure -> rule-based fallback
      4. Language always overridden by direct detection
    """

    def __init__(
        self,
        adapter_path: Optional[str] = None,
        use_model:    bool          = True,
    ):
        self.adapter_path  = adapter_path
        self.use_model     = use_model
        self.rule_parser   = RuleBasedParser()
        self.json_extractor = JSONExtractor()

        self._model        = None
        self._tokenizer    = None
        self._model_loaded = False

        if use_model:
            self._load_model()

    def _load_model(self) -> None:
        """
        Load base model + LoRA adapter.

        Adapter source from config.model.adapter_source:
          "hf"    -> PeftModel.from_pretrained(hf_lora_repo)
          "local" -> PeftModel.from_pretrained(local_path)
          "none"  -> base model only (for testing)

        HF_READ_TOKEN used for both base model and adapter authentication.
        """
        from config import settings

        adapter_source = settings.model.adapter_source

        # Validate HF token 
        hf_token = settings.hf.read_token if settings.hf.has_read_token else None
        if not hf_token:
            logger.warning(
                "hf_read_token_missing",
                note="Model loading may fail for gated repos. Set HF_READ_TOKEN in .env",
            )

        logger.info(
            "loading_intent_model",
            base_model=settings.model.name,
            adapter_source=adapter_source,
            adapter_path=self.adapter_path,
            hf_lora_repo=settings.model.hf_lora_repo or "(not set)",
        )

        try:
            # Quantization config  
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=settings.model.load_in_4bit,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type=settings.model.bnb_4bit_quant_type,
                bnb_4bit_use_double_quant=settings.model.use_nested_quant,
            )

            # Load base model 
            base_model = AutoModelForCausalLM.from_pretrained(
                settings.model.name,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True,
                token=hf_token,             # HF_READ_TOKEN for authentication
            )

            # Load tokenizer 
            self._tokenizer = AutoTokenizer.from_pretrained(
                settings.model.name,
                trust_remote_code=True,
                token=hf_token,             # same token for tokenizer
            )
            if self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token

            # Load LoRA adapter 
            if adapter_source == "hf":
                # Post-training: load from HF Hub
                adapter_id = settings.model.hf_lora_repo
                logger.info("loading_lora_from_hf", repo=adapter_id)
                self._model = PeftModel.from_pretrained(
                    base_model,
                    adapter_id,
                    token=hf_token,         # token for private HF repo
                )

            elif adapter_source == "local":
                # Dev mode: load from local path
                local_path = self.adapter_path or settings.model.lora_adapter_path
                logger.info("loading_lora_from_local", path=local_path)
                self._model = PeftModel.from_pretrained(
                    base_model,
                    local_path,
                )

            else:
                # No adapter — use base model only (for testing/dev)
                logger.warning(
                    "no_lora_adapter_found",
                    adapter_source=adapter_source,
                    note="Using base model only — intent quality will be lower",
                )
                self._model = base_model

            self._model.eval()
            self._model_loaded = True

            logger.info(
                "intent_model_loaded",
                adapter_source=adapter_source,
                device=str(next(self._model.parameters()).device),
            )

        except Exception as e:
            logger.error(
                "intent_model_load_failed",
                error=str(e),
                error_type=type(e).__name__,
                note="Will use rule-based parser only",
            )
            self._model_loaded = False

    def _build_prompt(self, text: str) -> str:
        """Build inference prompt matching training format exactly."""
        return (
            f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\n{text}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def _model_generate(self, text: str) -> str:
        """Run model inference. Returns raw string output."""
        from config import settings

        prompt = self._build_prompt(text)
        inputs = self._tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=400,
        ).to(self._model.device)

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=settings.model.max_new_tokens,
                # use temperature with do_sample=True 
                # do_sample=False (greedy) ignores temperature -> warning
                # Use do_sample=True with low temperature for determinism
                do_sample=True,
                temperature=settings.model.temperature,    # 0.1
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
            )

        # Decode only generated tokens (not the prompt)
        generated = outputs[0][inputs["input_ids"].shape[1]:]
        return self._tokenizer.decode(generated, skip_special_tokens=True)

    def parse(self, text: str) -> Intent:
        """
        Parse user text → Intent.
        Always returns a valid Intent — never raises.

        Pipeline:
          1. Model generate (if loaded)
          2. JSON extract + Pydantic validate
          3. Rule-based fallback (if model fails)
          4. Language detection override
          5. raw_text always set
        """
        start = time.time()
        text  = text.strip()

        if not text:
            return Intent(
                query_type=QueryType.UNKNOWN,
                language=Language.ARABIC,
                confidence=0.0,
                raw_text=text,
            )

        intent       = None
        parse_method = "unknown"

        # Step 1: Fine-tuned model  
        if self._model_loaded:
            try:
                raw_output = self._model_generate(text)
                json_data  = self.json_extractor.extract(raw_output)

                if json_data is not None:
                    # Remove raw_text from json_data to avoid duplicate kwarg
                    json_data.pop("raw_text", None)     # was crashing

                    intent       = Intent(**json_data, raw_text=text)
                    parse_method = "model"
                    logger.debug(
                        "model_parse_success",
                        text=text[:50],
                        query_type=intent.query_type,
                    )
                else:
                    logger.warning(
                        "model_no_json_extracted",
                        raw_output=raw_output[:200],
                        text=text[:50],
                    )

            except Exception as e:
                logger.warning(
                    "model_parse_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    text=text[:50],
                )

        # Step 2: Rule-based fallback 
        if intent is None:
            intent       = self.rule_parser.parse(text)
            parse_method = "rule_based"
            logger.info(
                "intent_rule_based_fallback",
                text=text[:50],
                query_type=intent.query_type,
            )

        # Step 3: Language detection override  
        # Model may misdetect language — always override with rule
        detected_lang = LanguageDetector.detect(text)
        if intent.language != detected_lang:
            # use model_copy() not direct mutation
            intent = intent.model_copy(update={"language": detected_lang})

        # Step 4: Ensure raw_text is always set 
        if not intent.raw_text:
            intent = intent.model_copy(update={"raw_text": text})

        elapsed_ms = round((time.time() - start) * 1000, 2)
        logger.info(
            "intent_parsed",
            query_type=intent.query_type,
            origin=intent.origin,
            destination=intent.destination,
            optimization=intent.optimization,
            method=parse_method,
            confidence=intent.confidence,
            elapsed_ms=elapsed_ms,
        )

        return intent

 

# Singleton factory 


_parser_instance: Optional[IntentParser] = None


def get_intent_parser(adapter_path: Optional[str] = None) -> IntentParser:
    """
    Return singleton IntentParser.

    Checks settings.model.adapter_source to decide loading strategy:
      "hf"    -> load from HF Hub (post-training)
      "local" -> load from local path (dev)
      "none"  -> rule-based only
    """
    global _parser_instance

    if _parser_instance is None:
        from config import settings

        adapter_source = settings.model.adapter_source

        logger.info(
            "initializing_intent_parser",
            adapter_source=adapter_source,
            hf_lora_repo=settings.model.hf_lora_repo or "(not set)",
            local_path=settings.model.lora_adapter_path,
        )

        if adapter_source == "none":
            # No adapter available -> rule-based only
            _parser_instance = IntentParser(
                adapter_path=None,
                use_model=False,
            )
        elif adapter_source == "hf":
            # Load from HF Hub — adapter_path not needed (uses settings.model.hf_lora_repo)
            _parser_instance = IntentParser(
                adapter_path=None,
                use_model=True,
            )
        else:
            # Load from local path
            _parser_instance = IntentParser(
                adapter_path=adapter_path or settings.model.lora_adapter_path,
                use_model=True,
            )

    return _parser_instance