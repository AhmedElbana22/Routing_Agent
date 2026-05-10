"""
dataset.py
Generates 1200+ training examples for Alexandria transport intent model.
"""

from __future__ import annotations

import json
import random
import re
import string
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from datasets import Dataset, DatasetDict

import sys
_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.append(str(_PROJECT_ROOT))

from data.raw.seed_examples import SEED_EXAMPLES
from model.intent.schema import Intent, QueryType, OptimizationGoal, Language

# Absolute output path  
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data" / "processed"

# Dataset save path (used by both dataset.py AND trainer.py)  
# Import this in trainer.py to guarantee path consistency
DATASET_SAVE_PATH = str(_DEFAULT_OUTPUT / "intent_dataset")


def get_dataset_path() -> str:
    """
    Returns the absolute path where the dataset is saved.
    
    Import this in trainer.py instead of hardcoding the path:
      from model.intent.dataset import get_dataset_path
      config = TrainingConfig(dataset_path=get_dataset_path())
    
    Guarantees trainer and dataset.py always agree on the path.
    Works in both local dev and Google Colab,, So flexiable to environment changes without hardcoded paths.
    """
    return DATASET_SAVE_PATH

 
# Alexandria stop names

ARABIC_STOPS = [
    "برج العرب", "العجمي", "العامرية", "كرموز", "المنشية",
    "محطة مصر", "محطة الرمل", "سيدي جابر", "الإبراهيمية", "سيدي بشر",
    "أبو قير", "العصافرة", "المنتزه", "القبة", "الدخيلة",
    "المعمورة", "ستانلي", "رشدي", "الشاطبي", "لوران",
    "ميدان التحرير", "وسط البلد", "الميناء", "الجمرك", "باكوس",
    "مصطفى كامل", "سيدي عبد الرحمن", "المفروزة", "فيكتوريا",
]

ENGLISH_STOPS = [ 
    "Borg Al-Arab", "Agami", "Amreya", "Karmous", "Manshia",
    "Misr Station", "Raml Station", "Sidi Gaber", "Ibrahimia", "Sidi Bishr",
    "Abu Qir", "Asafra", "Montaza", "Qobba", "Dekheila",
    "Maamoura", "Stanley", "Rushdy", "Shatby", "Laurent",
    "Tahrir Square", "Downtown", "Port", "Gomrok", "Bakos",
    "Mustafa Kamel", "Sidi Abd El Rahman", "Mafrouza", "Victoria",
]

 


# SYSTEM_PROMPT — must match inference.py EXACTLY 

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


def format_training_prompt(text: str, intent_dict: Dict[str, Any]) -> str:
    """
    Format single training example as Qwen2.5 chat prompt.
    MUST match inference.py _build_prompt() exactly.
    """
    intent_str = json.dumps(intent_dict, ensure_ascii=False, indent=2)
    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{text}<|im_end|>\n"
        f"<|im_start|>assistant\n{intent_str}<|im_end|>"
    )

 

# Journey templates 

AR_JOURNEY_TEMPLATES = [
    "عايز أروح من {origin} لـ{destination}",
    "عايز أروح من {origin} إلى {destination}",
    "محتاج أروح من {origin} لـ{destination}",
    "ازاي أوصل من {origin} لـ{destination}",
    "ازاي أوصل من {origin} إلى {destination}",
    "إيه أحسن طريق من {origin} لـ{destination}",
    "عاوز أسافر من {origin} لـ{destination}",
    "كيف أروح من {origin} لـ{destination}",
    "طريق من {origin} لـ{destination}",
    "رحلة من {origin} لـ{destination}",
    "أروح من {origin} إلى {destination} إزاي",
    "من {origin} لـ{destination} بأيه",
    "وصلني من {origin} لـ{destination}",
    "عايز أعدي من {origin} لـ{destination}",
]

EN_JOURNEY_TEMPLATES = [
    "I want to go from {origin} to {destination}",
    "How do I get from {origin} to {destination}",
    "How can I reach {destination} from {origin}",
    "route from {origin} to {destination}",
    "trip from {origin} to {destination}",
    "directions from {origin} to {destination}",
    "take me from {origin} to {destination}",
    "I need to travel from {origin} to {destination}",
    "what's the best way from {origin} to {destination}",
    "best route from {origin} to {destination}",
    "how to get from {origin} to {destination}",
]

AR_FAST_TEMPLATES = [
    "أسرع طريقة من {origin} لـ{destination}",
    "أسرع طريق من {origin} لـ{destination}",
    "عايز أوصل بأسرع وقت من {origin} لـ{destination}",
    "أسرع وسيلة من {origin} لـ{destination}",
    "بسرعة من {origin} لـ{destination}",
    "في أقل وقت من {origin} لـ{destination}",
    "مستعجل من {origin} لـ{destination}",
    "عاجل من {origin} لـ{destination}",
]

EN_FAST_TEMPLATES = [
    "fastest way from {origin} to {destination}",
    "quickest route from {origin} to {destination}",
    "fastest route from {origin} to {destination}",
    "get to {destination} from {origin} as fast as possible",
    "I'm in a hurry, from {origin} to {destination}",
    "minimum time from {origin} to {destination}",
    "express route from {origin} to {destination}",
]

AR_CHEAP_TEMPLATES = [
    "أرخص طريقة من {origin} لـ{destination}",
    "أرخص طريق من {origin} لـ{destination}",
    "عايز أوفر فلوس من {origin} لـ{destination}",
    "بأقل تمن من {origin} لـ{destination}",
    "أقل تكلفة من {origin} لـ{destination}",
    "اقتصادي من {origin} لـ{destination}",
    "بأقل مصروف من {origin} لـ{destination}",
    "أوفر طريقة من {origin} لـ{destination}",
]

EN_CHEAP_TEMPLATES = [
    "cheapest way from {origin} to {destination}",
    "cheapest route from {origin} to {destination}",
    "most affordable option from {origin} to {destination}",
    "budget option from {origin} to {destination}",
    "minimum cost from {origin} to {destination}",
    "low cost route from {origin} to {destination}",
    "save money traveling from {origin} to {destination}",
]

AR_FEWTRANSFERS_TEMPLATES = [
    "أقل تحويلات من {origin} لـ{destination}",
    "عايز أروح بأقل تحويلات من {origin} لـ{destination}",
    "مش عايز أغير كتير من {origin} لـ{destination}",
    "بدون تحويلات كتير من {origin} لـ{destination}",
    "طريق مريح من {origin} لـ{destination}",
    "أريح طريقة من {origin} لـ{destination}",
    "رحلة مباشرة من {origin} لـ{destination}",
]

EN_FEWTRANSFERS_TEMPLATES = [
    "minimum transfers from {origin} to {destination}",
    "fewest transfers from {origin} to {destination}",
    "least connections from {origin} to {destination}",
    "direct route from {origin} to {destination}",
    "most comfortable route from {origin} to {destination}",
    "no transfers if possible from {origin} to {destination}",
    "most direct from {origin} to {destination}",
]

AR_FOLLOWUP_TEMPLATES = [
    "طب وإيه لو {optimization_ar}؟",
    "وإيه لو {optimization_ar}؟",
    "طب {optimization_ar}؟",
    "جرب {optimization_ar}",
    "لو {optimization_ar} يبقى إيه؟",
    "عايز {optimization_ar}",
    "حولها لـ{optimization_ar}",
]

EN_FOLLOWUP_TEMPLATES = [
    "what if {optimization_en}?",
    "what about {optimization_en}?",
    "try {optimization_en} instead",
    "now show me {optimization_en}",
    "switch to {optimization_en}",
    "make it {optimization_en}",
]

OPTIMIZATION_AR_NAMES = {
    "min_time":      ["أسرع", "الأسرع", "أسرع طريقة", "أقل وقت"],
    "min_cost":      ["أرخص", "الأرخص", "أرخص طريقة", "أقل تمن"],
    "min_transfers": ["أقل تحويلات", "مفيش تحويلات", "طريق مريح", "أقل تغيير"],
    "balanced":      ["حاجة معقولة", "متوازن", "في الوسط"],
}
OPTIMIZATION_EN_NAMES = {
    "min_time":      ["fastest", "quickest", "minimum time"],
    "min_cost":      ["cheapest", "most affordable", "minimum cost"],
    "min_transfers": ["fewest transfers", "minimum transfers", "most direct"],
    "balanced":      ["balanced", "all factors", "middle ground"],
}

 


# Augmentation helpers 


def inject_typo(word: str, rate: float = 0.1) -> str:
    """Randomly inject a single typo into a word."""
    if len(word) < 3 or random.random() > rate:
        return word
    op = random.choice(["swap", "delete", "insert"])
    i  = random.randint(0, len(word) - 1)
    if op == "swap" and i < len(word) - 1:
        lst = list(word)
        lst[i], lst[i + 1] = lst[i + 1], lst[i]
        return "".join(lst)
    elif op == "delete":
        return word[:i] + word[i + 1:]
    else:
        return word[:i] + random.choice(string.ascii_lowercase) + word[i:]


def add_noise(text: str, rate: float = 0.05) -> str:
    """Add light noise to text for robustness training."""
    return " ".join(inject_typo(w, rate) for w in text.split())


def random_stop_pair(lang: str = "ar") -> Tuple[str, str]:
    """Return random distinct (origin, destination) pair."""
    stops = ARABIC_STOPS if lang == "ar" else ENGLISH_STOPS
    o, d  = random.sample(stops, 2)
    return o, d


def make_weight_vector(opt: str) -> Dict[str, float]:
    """Return normalized weight vector dict for an optimization goal."""
    presets = {
        "min_cost":      {"cost": 0.90, "time": 0.05, "transfers": 0.03, "walking": 0.02},
        "min_time":      {"cost": 0.05, "time": 0.90, "transfers": 0.03, "walking": 0.02},
        "min_transfers": {"cost": 0.05, "time": 0.10, "transfers": 0.80, "walking": 0.05},
        "min_walking":   {"cost": 0.05, "time": 0.10, "transfers": 0.10, "walking": 0.75},
        "balanced":      {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
    }
    return presets.get(opt, presets["balanced"])


# Confidence values per query_type  
# Teaches the model realistic uncertainty per intent type:
#   journey_request  -> high confidence (clear intent)
#   followup         -> medium (depends on context)
#   clarification    -> low  (model admits it doesn't know)
_CONFIDENCE_BY_QUERY_TYPE: Dict[str, float] = {
    "journey_request":      0.95,
    "followup":             0.85,
    "show_more":            0.90,
    "show_detail":          0.90,
    "info_request":         0.88,
    "clarification_needed": 0.30,
    "unknown":              0.20,
}


def _make_intent(
    query_type:   str,
    origin:       Optional[str],
    destination:  Optional[str],
    optimization: str,
    language:     str,
    confidence:   Optional[float] = None,   # if None -> use type default
    constraints:  Optional[list]  = None,
    result_index: Optional[int]   = None,
    info_target:  Optional[str]   = None,
    info_params:  Optional[dict]  = None,
) -> Dict[str, Any]:
    """
    Build a complete intent dict for training.

    confidence:
      - If explicitly passed, uses that value
      - If None, uses _CONFIDENCE_BY_QUERY_TYPE default
      - Teaches model realistic confidence per intent type
    
    also_report: intentionally excluded — not in SYSTEM_PROMPT schema
    raw_text:    intentionally excluded — not a model output field
    """
    # Use type-specific default confidence if not explicitly provided
    resolved_confidence = (
        confidence
        if confidence is not None
        else _CONFIDENCE_BY_QUERY_TYPE.get(query_type, 0.80)
    )
    return {
        "query_type":   query_type,
        "origin":       origin,
        "destination":  destination,
        "optimization": optimization,
        "weights":      make_weight_vector(optimization),
        "constraints":  constraints or [],
        "language":     language,
        "confidence":   resolved_confidence,
        "result_index": result_index,
        "info_target":  info_target,
        "info_params":  info_params or {},
    }

 

# Generator functions 


def generate_journey_examples(n: int = 200) -> List[Dict[str, Any]]:
    """Generate basic journey request examples (n/2 Arabic + n/2 English)."""
    examples = []
    for _ in range(n // 2):
        # Arabic
        o, d  = random_stop_pair("ar")
        text  = random.choice(AR_JOURNEY_TEMPLATES).format(origin=o, destination=d)
        if random.random() < 0.15:
            text = add_noise(text)
        examples.append({
            "text":   text,
            "intent": _make_intent("journey_request", o, d, "balanced", "ar"),
        })
        # English
        o_en, d_en = random_stop_pair("en")
        text       = random.choice(EN_JOURNEY_TEMPLATES).format(
            origin=o_en, destination=d_en
        )
        examples.append({
            "text":   text,
            "intent": _make_intent("journey_request", o_en, d_en, "balanced", "en"),
        })
    return examples


def generate_optimization_examples(n: int = 300) -> List[Dict[str, Any]]:
    """
    Generate optimization-specific examples.
    
    Count guarantee: generates exactly n examples (n // len(configs) * len(configs)).
    Remainder silently dropped — acceptable for training data.
    """
    examples = []
    configs = [
        ("ar", AR_FAST_TEMPLATES,          "min_time"),
        ("en", EN_FAST_TEMPLATES,          "min_time"),
        ("ar", AR_CHEAP_TEMPLATES,         "min_cost"),
        ("en", EN_CHEAP_TEMPLATES,         "min_cost"),
        ("ar", AR_FEWTRANSFERS_TEMPLATES,  "min_transfers"),
        ("en", EN_FEWTRANSFERS_TEMPLATES,  "min_transfers"),
    ]
    per_config = n // len(configs)   # 300 // 6 = 50 each
    for lang, templates, opt in configs:
        stops = ARABIC_STOPS if lang == "ar" else ENGLISH_STOPS
        for _ in range(per_config):
            o, d  = random.sample(stops, 2)
            text  = random.choice(templates).format(origin=o, destination=d)
            examples.append({
                "text":   text,
                "intent": _make_intent("journey_request", o, d, opt, lang),
            })
    # Actual count: per_config * len(configs) = 300 (exact for n=300)
    return examples


def generate_constrained_examples(n: int = 150) -> List[Dict[str, Any]]:
    """Generate examples with hard constraints (fare/duration limits)."""
    constraint_ar = [
        ("أسرع طريقة من {o} لـ{d} بس مش أكتر من {val} جنيه",
         "min_time",  {"field": "fare",     "operator": "lte"}),
        ("أرخص طريق من {o} لـ{d} في أقل من {val} دقيقة",
         "min_cost",  {"field": "duration", "operator": "lte"}),
        ("من {o} لـ{d} بأقل من {val} جنيه",
         "balanced",  {"field": "fare",     "operator": "lte"}),
        ("من {o} لـ{d} في {val} دقيقة بالكتير",
         "min_time",  {"field": "duration", "operator": "lte"}),
    ]
    constraint_en = [
        ("fastest from {o} to {d} but max {val} EGP",
         "min_time",  {"field": "fare",     "operator": "lte"}),
        ("cheapest from {o} to {d} under {val} minutes",
         "min_cost",  {"field": "duration", "operator": "lte"}),
        ("from {o} to {d} within {val} EGP budget",
         "balanced",  {"field": "fare",     "operator": "lte"}),
        ("get from {o} to {d} in under {val} minutes",
         "min_time",  {"field": "duration", "operator": "lte"}),
    ]
    fare_vals     = [10, 15, 20, 25]
    duration_vals = [30, 45, 60]

    examples = []
    for _ in range(n // 2):
        # Arabic
        o, d              = random_stop_pair("ar")
        tmpl, opt, c_base = random.choice(constraint_ar)
        val               = random.choice(
            fare_vals if c_base["field"] == "fare" else duration_vals
        )
        text       = tmpl.format(o=o, d=d, val=val)
        constraint = {**c_base, "value": float(val)}
        examples.append({
            "text":   text,
            "intent": _make_intent(
                "journey_request", o, d, opt, "ar",
                constraints=[constraint]
            ),
        })
        # English
        o_en, d_en        = random_stop_pair("en")
        tmpl, opt, c_base = random.choice(constraint_en)
        val               = random.choice(
            fare_vals if c_base["field"] == "fare" else duration_vals
        )
        text       = tmpl.format(o=o_en, d=d_en, val=val)
        constraint = {**c_base, "value": float(val)}
        examples.append({
            "text":   text,
            "intent": _make_intent(
                "journey_request", o_en, d_en, opt, "en",
                constraints=[constraint]
            ),
        })
    return examples


def generate_followup_examples(n: int = 150) -> List[Dict[str, Any]]:
    """Generate follow-up optimization change examples."""
    examples = []
    opts     = ["min_time", "min_cost", "min_transfers", "balanced"]
    for _ in range(n // 2):
        opt = random.choice(opts)
        # Arabic
        opt_name = random.choice(OPTIMIZATION_AR_NAMES.get(opt, ["حاجة تانية"]))
        text     = random.choice(AR_FOLLOWUP_TEMPLATES).format(optimization_ar=opt_name)
        examples.append({
            "text":   text,
            "intent": _make_intent("followup", None, None, opt, "ar"),
        })
        # English
        opt_name = random.choice(OPTIMIZATION_EN_NAMES.get(opt, ["something else"]))
        text     = random.choice(EN_FOLLOWUP_TEMPLATES).format(optimization_en=opt_name)
        examples.append({
            "text":   text,
            "intent": _make_intent("followup", None, None, opt, "en"),
        })
    return examples


def generate_show_more_examples(n: int = 80) -> List[Dict[str, Any]]:
    """Generate show-more / pagination examples."""
    ar_templates = [
        "وريني خيارات تانية", "فيه حاجة تانية؟", "عايز أشوف المزيد",
        "خيارات أكتر", "وريني الباقي", "غير ده إيه؟", "أكمل",
        "في خيارات تانية؟", "عايز أكتر من كده", "تاني إيه؟",
        "ومفيش غيرها؟", "كمّل معايا", "اعرضلي أكتر",
    ]
    en_templates = [
        "show me more options", "any other routes?", "more choices please",
        "what else is available", "show more", "other options?", "next",
        "see more", "are there more?", "continue", "more please",
        "what other routes exist", "give me more",
    ]
    examples = []
    for _ in range(n // 2):
        examples.append({
            "text":   random.choice(ar_templates),
            "intent": _make_intent("show_more", None, None, "balanced", "ar"),
        })
        examples.append({
            "text":   random.choice(en_templates),
            "intent": _make_intent("show_more", None, None, "balanced", "en"),
        })
    return examples


def generate_show_detail_examples(n: int = 80) -> List[Dict[str, Any]]:
    """
    Generate show-detail examples.
    result_index is 1-BASED — matches agent.py and inference.py.
    """
    ar_templates = [
        ("فيه تفاصيل أكتر عن الأول؟",      1),
        ("وضح لي الرحلة الأولى",            1),
        ("تفاصيل رقم 1",                    1),
        ("عايز أعرف أكتر عن الأولى",        1),
        ("الرحلة الأولى إيه تفاصيلها؟",     1),
        ("فيه تفاصيل أكتر عن التانية؟",     2),
        ("وضح لي الرحلة التانية",           2),
        ("تفاصيل رقم 2",                    2),
        ("عايز أعرف أكتر عن التانية",       2),
        ("الخيار التالت إيه تفاصيله؟",      3),
        ("وضح لي الخيار التالت",            3),
        ("تفاصيل رقم 3",                    3),
        ("الثالثة إيه فيها؟",               3),
    ]
    en_templates = [
        ("tell me more about option 1",      1),
        ("details about the first route",    1),
        ("expand on option 1",               1),
        ("more info on journey 1",           1),
        ("what's in route number 1",         1),
        ("tell me more about option 2",      2),
        ("details about the second route",   2),
        ("expand on option 2",               2),
        ("more info on journey 2",           2),
        ("what about option 3 in detail?",   3),
        ("expand on the third option",       3),
        ("details about route 3",            3),
        ("tell me about number 3",           3),
    ]
    examples = []
    for _ in range(n // 2):
        ar_text, ar_idx = random.choice(ar_templates)
        examples.append({
            "text":   ar_text,
            "intent": _make_intent(
                "show_detail", None, None, "balanced", "ar",
                result_index=ar_idx,
            ),
        })
        en_text, en_idx = random.choice(en_templates)
        examples.append({
            "text":   en_text,
            "intent": _make_intent(
                "show_detail", None, None, "balanced", "en",
                result_index=en_idx,
            ),
        })
    return examples


def generate_info_request_examples(n: int = 100) -> List[Dict[str, Any]]:
    """
    Generate fare/schedule/line info request examples.
    
    Count: generates exactly n examples total.
    Each loop iteration adds 4 examples → n // 4 iterations.
    If n is not divisible by 4, last few are dropped (acceptable).
    """
    line_ids = [
        "I46ZQc9g0OMvTpnnq0RXs",
        "tv4mLSYvBC5Q4aSnL5h83",
        "microbus_1", "microbus_2", "microbus_3",
        "10", "20", "30", "42",
    ]
    ar_fare_templates = [
        "كام تعريفة خط {line}؟",
        "بكام خط {line}؟",
        "سعر تذكرة خط {line}",
        "تمن الركوب في خط {line}",
        "كام أجرة خط {line}؟",
        "الخط {line} بكام؟",
    ]
    ar_schedule_templates = [
        "مواعيد خط {line}",
        "امتى أول ميكروباص خط {line}؟",
        "مواعيد رحلات خط {line}",
        "خط {line} بيشتغل امتى؟",
        "امتى آخر خط {line}؟",
    ]
    en_fare_templates = [
        "what is the fare for line {line}?",
        "how much does line {line} cost?",
        "price of line {line}",
        "ticket cost for line {line}",
        "how much is line {line}?",
    ]
    en_schedule_templates = [
        "schedule for line {line}",
        "when does line {line} run?",
        "operating hours for line {line}",
        "what time does line {line} start?",
        "last microbus on line {line}?",
    ]

    examples = []
    # Each iteration produces exactly 4 examples
    # n // 4 iterations → n examples (floor division)
    for _ in range(n // 4):
        line = random.choice(line_ids)
        examples.append({
            "text":   random.choice(ar_fare_templates).format(line=line),
            "intent": _make_intent(
                "info_request", None, None, "balanced", "ar",
                info_target="fare", info_params={"line_id": line},
            ),
        })
        examples.append({
            "text":   random.choice(ar_schedule_templates).format(line=line),
            "intent": _make_intent(
                "info_request", None, None, "balanced", "ar",
                info_target="schedule", info_params={"line_id": line},
            ),
        })
        examples.append({
            "text":   random.choice(en_fare_templates).format(line=line),
            "intent": _make_intent(
                "info_request", None, None, "balanced", "en",
                info_target="fare", info_params={"line_id": line},
            ),
        })
        examples.append({
            "text":   random.choice(en_schedule_templates).format(line=line),
            "intent": _make_intent(
                "info_request", None, None, "balanced", "en",
                info_target="schedule", info_params={"line_id": line},
            ),
        })
    return examples   # exact count: (n // 4) * 4


def generate_clarification_examples(n: int = 60) -> List[Dict[str, Any]]:
    """
    Generate clarification_needed examples.
    Low confidence (0.30) — model learns these are ambiguous inputs.
    """
    ar_ambiguous = [
        "عايز أروح",
        "ازاي أوصل؟",
        "الرحلة دي تمن كام؟",
        "أسرع",
        "المشوار ده",
        "روح وجيب",
        "ممكن تساعدني؟",
        "أيه الأحسن؟",
    ]
    en_ambiguous = [
        "I want to go",
        "how do I get there?",
        "what's the price?",
        "fastest",
        "help me",
        "the journey",
        "is it available?",
        "how much?",
    ]
    examples = []
    for _ in range(n // 2):
        examples.append({
            "text":   random.choice(ar_ambiguous),
            "intent": _make_intent(
                "clarification_needed", None, None, "balanced", "ar",
            ),
        })
        examples.append({
            "text":   random.choice(en_ambiguous),
            "intent": _make_intent(
                "clarification_needed", None, None, "balanced", "en",
            ),
        })
    return examples


def generate_mixed_language_examples(n: int = 80) -> List[Dict[str, Any]]:
    """
    Generate Arabic-English code-switched examples.
    origin/destination determined from template metadata (not string inspection).
    """
    # (template, query_type, optimization, origin_lang, dest_lang)
    # origin_lang/dest_lang: "ar" | "en" | None
    templates = [
        ("عايز أروح من {o_ar} لـ{d_en}",           "journey_request",      "balanced",   "ar", "en"),
        ("أسرع route من {o_ar} لـ{d_ar}",           "journey_request",      "min_time",   "ar", "ar"),
        ("cheapest طريقة من {o_en} لـ{d_ar}",       "journey_request",      "min_cost",   "en", "ar"),
        ("عايز أروح {o_en} to {d_en} بالـ microbus","journey_request",      "balanced",   "en", "en"),
        ("what if أرخص؟",                           "followup",             "min_cost",   None, None),
        ("show me أسرع option",                      "followup",             "min_time",   None, None),
        ("وريني more options",                       "show_more",            "balanced",   None, None),
        ("كام الfare؟",                              "clarification_needed", "balanced",   None, None),
    ]
    examples = []
    for _ in range(n):
        tmpl, qtype, opt, o_lang, d_lang = random.choice(templates)

        o_ar, d_ar = random_stop_pair("ar")
        o_en, d_en = random_stop_pair("en")

        text = tmpl.format(o_ar=o_ar, d_ar=d_ar, o_en=o_en, d_en=d_en)

        # Determine origin/destination from template metadata
        origin      = o_ar if o_lang == "ar" else (o_en if o_lang == "en" else None)
        destination = d_ar if d_lang == "ar" else (d_en if d_lang == "en" else None)

        info_target = (
            "fare"
            if "fare" in text.lower() or "تعريفة" in text
            else None
        )

        examples.append({
            "text":   text,
            "intent": _make_intent(
                qtype, origin, destination, opt, "mixed",
                info_target=info_target,
            ),
        })
    return examples


# ─────────────────────────────────────────────────────────────────────────────
# Seed example validation
# ─────────────────────────────────────────────────────────────────────────────


def _validate_seed_examples(seeds: List[Any]) -> List[Dict[str, Any]]:
    """
    Validate SEED_EXAMPLES format before adding to dataset.
    
    Each seed must be a dict with:
      - "text"   : str (non-empty user input)
      - "intent" : dict (valid intent fields)
    
    Invalid seeds are skipped with a warning (not a crash).
    This prevents a bad seed file from corrupting the whole dataset.
    """
    valid   = []
    skipped = 0
    for i, seed in enumerate(seeds):
        # Check type
        if not isinstance(seed, dict):
            skipped += 1
            if skipped <= 3:
                print(f"  [SEED SKIP #{i}] Not a dict: {type(seed)}")
            continue
        # Check required keys
        if "text" not in seed or "intent" not in seed:
            skipped += 1
            if skipped <= 3:
                print(f"  [SEED SKIP #{i}] Missing 'text' or 'intent' key: {list(seed.keys())}")
            continue
        # Check text is non-empty string
        if not isinstance(seed["text"], str) or not seed["text"].strip():
            skipped += 1
            if skipped <= 3:
                print(f"  [SEED SKIP #{i}] Empty or non-string text")
            continue
        # Check intent is a dict
        if not isinstance(seed["intent"], dict):
            skipped += 1
            if skipped <= 3:
                print(f"  [SEED SKIP #{i}] intent is not a dict: {type(seed['intent'])}")
            continue
        valid.append(seed)

    if skipped > 0:
        print(f"  [Seeds] Skipped {skipped} invalid seed examples "
              f"({len(valid)} valid out of {len(seeds)} total)")
    else:
        print(f"  [Seeds] All {len(valid)} seed examples valid ✅")

    return valid


# ─────────────────────────────────────────────────────────────────────────────
# Main dataset builder
# ─────────────────────────────────────────────────────────────────────────────


class DatasetBuilder:
    """
    Builds the full training dataset from seeds + augmentation.
    Target: 1200+ examples with 90/10 train/val split.
    
    Output: saves to DATASET_SAVE_PATH (importable constant)
    Use get_dataset_path() in trainer.py to find the dataset.
    """

    def __init__(
        self,
        output_dir:   str = str(_DEFAULT_OUTPUT),
        seed:         int = 42,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.seed = seed
        # Note: random.seed() called in build() not here
        # Ensures reproducibility even if other code runs between init and build()

    def build(self) -> DatasetDict:
        """Build, validate, split, and save the dataset."""
        # Seed here — right before generation, not at init
        random.seed(self.seed)

        print(f"Building Alexandria transport intent dataset...")
        print(f"Seed: {self.seed}")
        print(f"Output: {self.output_dir}")

        # 1. Collect all examples 
        print("\n[Step 1] Collecting examples...")

        # Validate seeds before adding — fail safely
        validated_seeds = _validate_seed_examples(SEED_EXAMPLES)

        all_examples = []
        all_examples.extend(validated_seeds)
        all_examples.extend(generate_journey_examples(200))
        all_examples.extend(generate_optimization_examples(300))
        all_examples.extend(generate_constrained_examples(150))
        all_examples.extend(generate_followup_examples(150))
        all_examples.extend(generate_show_more_examples(80))
        all_examples.extend(generate_show_detail_examples(80))
        all_examples.extend(generate_info_request_examples(100))
        all_examples.extend(generate_clarification_examples(60))
        all_examples.extend(generate_mixed_language_examples(80))

        print(f"Raw examples collected: {len(all_examples)}")

        # 2. Deduplicate by normalized text  
        print("\n[Step 2] Deduplicating...")
        seen:   set        = set()
        unique: List[Dict] = []
        for ex in all_examples:
            key = re.sub(r"\s+", " ", ex["text"].strip().lower())
            if key not in seen:
                seen.add(key)
                unique.append(ex)
        print(f"After dedup: {len(unique)}")

        # 3. Validate with Pydantic 
        print("\n[Step 3] Validating with Pydantic schema...")
        valid:   List[Dict] = []
        skipped: int        = 0
        for ex in unique:
            try:
                # Remove fields Intent doesn't accept at construction
                intent_data = {
                    k: v for k, v in ex["intent"].items()
                    if k not in ("raw_text", "also_report")
                }
                Intent(**intent_data)
                valid.append(ex)
            except Exception as e:
                skipped += 1
                if skipped <= 5:
                    print(f"  [SKIP] {ex['text'][:60]} — {e}")
        if skipped > 5:
            print(f"  ... and {skipped - 5} more skipped")
        print(f"After validation: {len(valid)} examples")

        # 4. Format as training prompts
        print("\n[Step 4] Formatting as training prompts...")
        formatted: List[Dict] = []
        for ex in valid:
            prompt = format_training_prompt(ex["text"], ex["intent"])
            formatted.append({
                "text":       prompt,             # "text" field used by trainer
                "raw_input":  ex["text"],
                "query_type": ex["intent"]["query_type"],
                "language":   ex["intent"].get("language", "ar"),
            })

        # 5. Shuffle 
        random.shuffle(formatted)

        # 6. 90/10 train/val split 
        split_idx  = int(len(formatted) * 0.9)
        train_data = formatted[:split_idx]
        val_data   = formatted[split_idx:]

        # 7. Create HuggingFace DatasetDict
        dataset = DatasetDict({
            "train":      Dataset.from_list(train_data),
            "validation": Dataset.from_list(val_data),
        })

        # 8. Save to disk  
        print("\n[Step 8] Saving dataset...")
        save_path = self.output_dir / "intent_dataset"
        dataset.save_to_disk(str(save_path))
        print(f"Dataset saved → {save_path}")
        print(f"Import path  → get_dataset_path() returns: '{DATASET_SAVE_PATH}'")

        # 9. Save raw JSON for inspection  
        json_path = self.output_dir / "all_examples.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(valid, f, ensure_ascii=False, indent=2)
        print(f"Raw JSON     → {json_path}")

        # 10. Print stats 
        self._print_stats(valid, train_data, val_data)

        return dataset

    def _print_stats(
        self,
        examples: List[Dict],
        train:    List[Dict],
        val:      List[Dict],
    ) -> None:
        qt_counts   = Counter(e["intent"]["query_type"] for e in examples)
        lang_counts = Counter(e["intent"].get("language", "ar") for e in examples)

        print("\n" + "=" * 55)
        print("  ALEXANDRIA INTENT DATASET STATISTICS")
        print("=" * 55)
        print(f"  Total examples : {len(examples)}")
        print(f"  Train split    : {len(train)}  ({len(train)/len(examples)*100:.0f}%)")
        print(f"  Val split      : {len(val)}    ({len(val)/len(examples)*100:.0f}%)")
        print("\n  Query type distribution:")
        for qt, count in qt_counts.most_common():
            bar = "█" * int(count / len(examples) * 30)
            print(f"    {qt:<25} {count:>4}  {bar}")
        print("\n  Language distribution:")
        for lang, count in lang_counts.most_common():
            print(f"    {lang:<10} {count:>4}  ({count/len(examples)*100:.1f}%)")
        print("=" * 55)


if __name__ == "__main__":
    builder = DatasetBuilder()
    ds = builder.build()
    print(f"\nDone. Train: {len(ds['train'])}, Val: {len(ds['validation'])}")