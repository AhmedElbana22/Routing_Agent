"""
response_builder.py
Converts ranked Journey objects + Intent → natural language strings.

Bilingual: Arabic, English, Mixed.
Uses Arabic stop/line names from Step.line_name_ar / from_stop_name_ar.
Handles all agent response scenarios:
  build_journey_response()   — initial + re-ranked results
  build_followup_response()  — optimization change
  build_pagination_response()— show_more (pagination)
  build_detail_response()    — single journey step-by-step
  build_info_response()      — fare / schedule / line_info
  ask_missing()              — prompt for missing fields
  stop_not_found()           — stop resolution failure
  no_route_found()           — routing engine returned nothing
  no_more_results()          — show_more at end of results
  no_context()               — followup without active journeys
  clarify()                  — unknown intent
  api_error()                — server error
  all_filtered()             — constraints filtered everything
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.append(str(Path(__file__).parent.parent))

from model.intent.schema import (
    Intent,
    Journey,
    Language,
    QueryType,
    Step,
    TransportMode,
)
import structlog

logger = structlog.get_logger(__name__)



# Templates


TEMPLATES: Dict[Language, Dict[str, str]] = {

    Language.ARABIC: {
        #  Journey results 
        "journey_header":          "أفضل {n} رحلة من {origin} لـ{destination}:\n\n",
        "journey_header_followup": "بعد التعديل، أحسن {n} رحلات:\n\n",
        "journey_header_more":     "الخيارات التالية:\n\n",   # pagination

        "journey_item": (
            "#{rank}. {line_summary}\n"
            "   ⏱ {duration} دقيقة  |  💰 {fare} جنيه  |  🔄 {transfers} تحويلة\n"
            "   📍 {reason}\n"
        ),
        "journey_footer":         "\nقول 'وريني أكتر' للمزيد من الخيارات.",
        "journey_footer_no_more": "\nده كل الخيارات المتاحة.",

        #  Detail view 
        "detail_header":       "تفاصيل الرحلة #{rank}:\n\n",
        "detail_stats": (
            "المدة: {duration} دقيقة\n"
            "السعر: {fare} جنيه\n"
            "التحويلات: {transfers}\n"
            "المشي: {walking} متر\n\n"
        ),
        "detail_steps_header": "خطوات الرحلة:\n",
        "detail_step":         "  {idx}. {step_text}\n",
        "detail_reason":       "\nسبب الاختيار: {reason}",

        #  Steps 
        "step_transit": "اركب {line_name} من {from_stop} لـ{to_stop}",
        "step_walk":    "امشي من {from_stop} لـ{to_stop} ({distance} متر)",
        "line_summary_direct": "مشي مباشر",   # ← NEW: Arabic "Direct"

        #  Info responses 
        "fare_response":      "تعريفة {line_name}: {fare} جنيه",
        "fare_ml_note":       " (تقدير)",           #  ML predicted note
        "schedule_response":  "مواعيد {line_name}: يبدأ {start} وينتهي {end}",
        "schedule_days":      "أيام الخدمة: {days}",
        "line_info_header":   "معلومات {line_name}:\n",
        "line_info_mode":     "النوع: {mode}\n",
        "line_info_operator": "المشغل: {operator}\n",
        "line_info_fare":     "التعريفة: {fare} جنيه\n",
        "line_info_trips":    "عدد الرحلات: {n} رحلات\n",
        "info_not_found":     "معندكش معلومات عن {target} لـ{line_id}.",

        #  Errors & prompts 
        "ask_origin":       "تبدأ منين؟",
        "ask_destination":  "عايز تروح فين؟",
        "ask_both":         "تبدأ منين وعايز تروح فين؟",
        "stop_not_found":   "مش عارف أعرف '{stop}'. ممكن تكتبه تاني أو تقول أقرب منطقة ليه؟",
        "no_route":         "مفيش رحلة متاحة من {origin} لـ{destination} دلوقتي.",
        "no_more":          "مفيش خيارات تانية متاحة.",
        "no_context":       "مش فاهم تعديل على إيه. ابدأ بسؤال رحلة الأول.",
        "clarify":          "مش فاهم. ممكن تسأل زي: 'عايز أروح من العصافرة لسيدي بشر'؟",
        "api_error":        "في مشكلة في السيرفر. حاول تاني.",
        "all_filtered":     "مفيش رحلة بالشروط دي. عندك خيارات تانية بس بدون قيود:",
    },

    Language.ENGLISH: {
        #  Journey results 
        "journey_header":          "Top {n} journeys from {origin} to {destination}:\n\n",
        "journey_header_followup": "Updated results — top {n} journeys:\n\n",
        "journey_header_more":     "More options:\n\n",    # ← NEW: pagination

        "journey_item": (
            "#{rank}. {line_summary}\n"
            "   ⏱ {duration} min  |  💰 {fare} EGP  |  🔄 {transfers} transfer(s)\n"
            "   📍 {reason}\n"
        ),
        "journey_footer":         "\nSay 'show more' for additional options.",
        "journey_footer_no_more": "\nThose are all available options.",

        #  Detail view 
        "detail_header":       "Details for Journey #{rank}:\n\n",
        "detail_stats": (
            "Duration:  {duration} min\n"
            "Fare:      {fare} EGP\n"
            "Transfers: {transfers}\n"
            "Walking:   {walking}m\n\n"
        ),
        "detail_steps_header": "Step by step:\n",
        "detail_step":         "  {idx}. {step_text}\n",
        "detail_reason":       "\nWhy ranked #{rank}: {reason}",

        #  Steps 
        "step_transit":         "Take {line_name} from {from_stop} to {to_stop}",
        "step_walk":            "Walk from {from_stop} to {to_stop} ({distance}m)",
        "line_summary_direct":  "Direct walk",

        #  Info responses 
        "fare_response":      "Fare for {line_name}: {fare} EGP",
        "fare_ml_note":       " (estimated)",
        "schedule_response":  "Schedule for {line_name}: runs {start} to {end}",
        "schedule_days":      "Service days: {days}",
        "line_info_header":   "Info for {line_name}:\n",
        "line_info_mode":     "Mode: {mode}\n",
        "line_info_operator": "Operator: {operator}\n",
        "line_info_fare":     "Fare: {fare} EGP\n",
        "line_info_trips":    "Trips: {n}\n",
        "info_not_found":     "No info found for {target} on {line_id}.",

        #  Errors & prompts 
        "ask_origin":       "Where are you departing from?",
        "ask_destination":  "Where do you want to go?",
        "ask_both":         "Where are you traveling from and to?",
        "stop_not_found":   "I couldn't find '{stop}'. Could you rephrase or mention a nearby area?",
        "no_route":         "No available route from {origin} to {destination} right now.",
        "no_more":          "No more options available.",
        "no_context":       "Not sure what to update. Please start with a journey request first.",
        "clarify":          "I didn't understand that. Try: 'I want to go from Asafra to Sidi Bishr'.",
        "api_error":        "Server error. Please try again.",
        "all_filtered":     "No journey matches your constraints. Here are options without restrictions:",
    },

    Language.MIXED: {
        # Mixed — Arabic text, EGP units visible, English transport terms
        "journey_header":          "أفضل {n} رحلة من {origin} لـ{destination}:\n\n",
        "journey_header_followup": "بعد التعديل، أحسن {n} رحلات:\n\n",
        "journey_header_more":     "خيارات تانية:\n\n",
        "journey_item": (
            "#{rank}. {line_summary}\n"
            "   ⏱ {duration} دقيقة  |  💰 {fare} EGP  |  🔄 {transfers} transfer(s)\n"
            "   📍 {reason}\n"
        ),
        "journey_footer":          "\nقول 'show more' للمزيد.",
        "journey_footer_no_more":  "\nده كل الخيارات المتاحة.",
        "detail_header":           "تفاصيل الرحلة #{rank}:\n\n",
        "detail_stats": (
            "المدة: {duration} دقيقة\n"
            "السعر: {fare} EGP\n"
            "التحويلات: {transfers}\n"
            "المشي: {walking} متر\n\n"
        ),
        "detail_steps_header":     "خطوات الرحلة:\n",
        "detail_step":             "  {idx}. {step_text}\n",
        "detail_reason":           "\nسبب الاختيار: {reason}",
        "step_transit":            "اركب {line_name} من {from_stop} لـ{to_stop}",
        "step_walk":               "امشي من {from_stop} لـ{to_stop} ({distance}m)",
        "line_summary_direct":     "مشي مباشر",
        "fare_response":           "تعريفة {line_name}: {fare} EGP",
        "fare_ml_note":            " (تقدير)",
        "schedule_response":       "مواعيد {line_name}: يبدأ {start} وينتهي {end}",
        "schedule_days":           "أيام الخدمة: {days}",
        "line_info_header":        "معلومات {line_name}:\n",
        "line_info_mode":          "النوع: {mode}\n",
        "line_info_operator":      "المشغل: {operator}\n",
        "line_info_fare":          "التعريفة: {fare} EGP\n",
        "line_info_trips":         "عدد الرحلات: {n}\n",
        "info_not_found":          "معندكش معلومات عن {target} لـ{line_id}.",
        "ask_origin":              "تبدأ منين؟",
        "ask_destination":         "عايز تروح فين؟",
        "ask_both":                "تبدأ منين وعايز تروح فين؟",
        "stop_not_found":          "مش عارف أعرف '{stop}'. ممكن تكتبه تاني؟",
        "no_route":                "مفيش رحلة من {origin} لـ{destination} دلوقتي.",
        "no_more":                 "مفيش خيارات تانية.",
        "no_context":              "مش فاهم تعديل على إيه. ابدأ بسؤال رحلة الأول.",
        "clarify":                 "مش فاهم. حاول تاني.",
        "api_error":               "في مشكلة. حاول تاني.",
        "all_filtered":            "مفيش رحلة بالشروط دي. خيارات بدون قيود:",
    },
}


MODE_NAMES_AR = {
    "microbus": "ميكروباص",
    "bus":      "أتوبيس",
    "metro":    "مترو",
    "tram":     "ترام",
    "walk":     "مشي",
}


# Template helper
 

def _t(language: Language, key: str) -> str:
    """
    Get template for language + key.
    Falls back to Arabic if language not in TEMPLATES.
    Falls back to key name if template missing.
    """
    lang_tpl = TEMPLATES.get(language, TEMPLATES[Language.ARABIC])
    result   = lang_tpl.get(key)
    if result is None:
        result = TEMPLATES[Language.ARABIC].get(key, f"[{key}]")
    return result


 
# Line summary builder — bilingual
 

def _build_line_summary(journey: Journey, language: Language = Language.ARABIC) -> str:
    """
    Build compact line summary from journey steps.

    Uses Arabic line names when language is Arabic/Mixed.
    Examples:
      AR: "ميكروباص → ميكروباص"
      EN: "Microbus 72 → Microbus 55"
    """
    transit_steps = [
        s for s in journey.steps
        if s.mode != TransportMode.WALK
    ]

    if not transit_steps:
        return _t(language, "line_summary_direct")   # ← language-aware

    use_arabic = language in (Language.ARABIC, Language.MIXED)
    parts = []


    for step in transit_steps:
        if use_arabic:
            name = (
                step.line_name_ar
                or step.headsign_ar
                or step.line_name
                or step.headsign
                or MODE_NAMES_AR.get(step.mode.value, "ميكروباص")  # ← mode name fallback
            )
        else:
            name = (
                step.line_name
                or step.headsign
                or step.mode.value.capitalize()   # ← "Microbus", "Bus", "Metro"
            )
        parts.append(name)

    return " → ".join(parts)


 
# Step name helpers — bilingual
 

def _stop_name(step: Step, field: str, language: Language) -> str:
    """
    Get stop name for display — Arabic if available and language is Arabic.

    field: "from" or "to"
    """
    use_arabic = language in (Language.ARABIC, Language.MIXED)

    if field == "from":
        ar_name = step.from_stop_name_ar
        en_name = step.from_stop_name
    else:
        ar_name = step.to_stop_name_ar
        en_name = step.to_stop_name

    if use_arabic and ar_name:
        return ar_name
    return en_name or "?"


def _line_name(step: Step, language: Language) -> str:
    use_arabic = language in (Language.ARABIC, Language.MIXED)
    if use_arabic:
        return (
            step.line_name_ar
            or step.headsign_ar
            or step.line_name
            or step.headsign
            or MODE_NAMES_AR.get(step.mode.value, "ميكروباص")
        )
    return (
        step.line_name
        or step.headsign
        or step.mode.value.capitalize()
    )


 
# Response Builder
 

class ResponseBuilder:
    """
    Converts Journey objects + Intent → natural language strings.
    Fully bilingual (Arabic / English / Mixed).
    """

    #  Journey responses 

    def build_journey_response(
        self,
        journeys:    List[Journey],
        intent:      Optional[Intent],
        has_more:    bool = False,
        is_followup: bool = False,
    ) -> str:
        """
        Build main journey results response.
        Used for initial search and re-ranking (followup).
        """
        lang   = intent.language if intent else Language.ARABIC
        origin = (intent.origin or "?")      if intent else "?"
        dest   = (intent.destination or "?") if intent else "?"
        n      = len(journeys)

        if not journeys:
            return _t(lang, "no_route").format(origin=origin, destination=dest)

        #  Header 
        if is_followup:
            header = _t(lang, "journey_header_followup").format(n=n)
        else:
            header = _t(lang, "journey_header").format(
                n=n, origin=origin, destination=dest
            )

        #  Journey items 
        items = []
        for journey in journeys:
            line_summary = _build_line_summary(journey, lang)
            item = _t(lang, "journey_item").format(
                rank=journey.rank,
                line_summary=line_summary,
                duration=int(journey.total_duration_minutes),
                fare=f"{journey.total_fare_egp:.0f}",
                transfers=journey.transfers,
                reason=journey.rank_reason or "",
            )
            items.append(item)

        #  Footer 
        footer = (
            _t(lang, "journey_footer")
            if has_more
            else _t(lang, "journey_footer_no_more")
        )

        return header + "\n".join(items) + footer

    def build_followup_response(
        self,
        journeys:    List[Journey],
        intent:      Optional[Intent],
        has_more:    bool = False,
    ) -> str:
        """Build response for re-ranking follow-up."""
        return self.build_journey_response(
            journeys=journeys,
            intent=intent,
            has_more=has_more,
            is_followup=True,
        )

    def build_pagination_response(
        self,
        journeys:    List[Journey],
        intent:      Optional[Intent],
        has_more:    bool = False,
    ) -> str:
        """
        Build response for show_more (pagination).
        Uses 'journey_header_more' — no origin/destination repeat.
        """
        lang = intent.language if intent else Language.ARABIC

        if not journeys:
            return self.no_more_results(lang)

        #  use pagination header not full journey header
        header = _t(lang, "journey_header_more")

        items = []
        for journey in journeys:
            line_summary = _build_line_summary(journey, lang)
            item = _t(lang, "journey_item").format(
                rank=journey.rank,
                line_summary=line_summary,
                duration=int(journey.total_duration_minutes),
                fare=f"{journey.total_fare_egp:.0f}",
                transfers=journey.transfers,
                reason=journey.rank_reason or "",
            )
            items.append(item)

        footer = (
            _t(lang, "journey_footer")
            if has_more
            else _t(lang, "journey_footer_no_more")
        )

        return header + "\n".join(items) + footer

    #  Detail view 

    def build_detail_response(
        self,
        journey: Journey,
        intent:  Optional[Intent],
    ) -> str:
        """Build step-by-step detail for a single journey."""
        lang = intent.language if intent else Language.ARABIC

        #  Header 
        response = _t(lang, "detail_header").format(rank=journey.rank)

        #  Summary stats 
        response += _t(lang, "detail_stats").format(
            duration=int(journey.total_duration_minutes),
            fare=f"{journey.total_fare_egp:.0f}",
            transfers=journey.transfers,
            walking=int(journey.total_walking_meters),
        )

        #  Steps — bilingual stop/line names 
        response += _t(lang, "detail_steps_header")
        for idx, step in enumerate(journey.steps, 1):
            if step.mode == TransportMode.WALK:
                step_text = _t(lang, "step_walk").format(
                    from_stop=_stop_name(step, "from", lang),  # ← bilingual
                    to_stop=_stop_name(step, "to",   lang),    # ← bilingual
                    distance=int(step.distance_meters),
                )
            else:
                step_text = _t(lang, "step_transit").format(
                    line_name=_line_name(step, lang),           # ← bilingual
                    from_stop=_stop_name(step, "from", lang),   # ← bilingual
                    to_stop=_stop_name(step, "to",   lang),     # ← bilingual
                )

            response += _t(lang, "detail_step").format(
                idx=idx,
                step_text=step_text,
            )

        #  Reason 
        if journey.rank_reason:
            response += _t(lang, "detail_reason").format(
                rank=journey.rank,
                reason=journey.rank_reason,
            )

        return response

    #  Info responses 

    def build_info_response(
        self,
        info_data:   Optional[Dict[str, Any]],
        info_target: str,
        info_params: Dict[str, Any],
        language:    Language = Language.ARABIC,
    ) -> str:
        """
        Build response for info_request (fare / schedule / line_info).

        Handles actual keys from db_tool responses:
          fare:      {"estimated_fare": 8.0, "fare_basis": "ml_predicted", ...}
          schedule:  {"route_name": ..., "first_arrival": ..., "last_departure": ...}
          line_info: {"route_name": ..., "mode": ..., "trips": [...], ...}
        """
        line_id = info_params.get("line_id", "?")

        if info_data is None:
            return _t(language, "info_not_found").format(
                target=info_target,
                line_id=line_id,
            )

        #  Fare 
        if info_target == "fare":
            # actual key is "estimated_fare" not "fare"/"price"
            fare        = info_data.get("estimated_fare", "?")
            fare_basis  = info_data.get("fare_basis", "")
            line_name   = info_data.get("route_name", line_id)
            ml_note     = _t(language, "fare_ml_note") if fare_basis == "ml_predicted" else ""

            return _t(language, "fare_response").format(
                line_name=line_name,
                fare=f"{float(fare):.0f}" if fare != "?" else "?",
            ) + ml_note

        #  Schedule 
        if info_target == "schedule":
            # ← Fixed: actual key is "first_arrival" not "first_departure"
            start     = info_data.get("first_arrival", "?")
            end       = info_data.get("last_departure", "?")
            line_name = info_data.get("route_name", line_id)

            schedule_text = _t(language, "schedule_response").format(
                line_name=line_name,
                start=start,
                end=end,
            )

            # Add service days if available
            service_days = info_data.get("service_days", [])
            if service_days:
                days_str = ", ".join(str(d) for d in service_days)
                schedule_text += "\n" + _t(language, "schedule_days").format(
                    days=days_str
                )

            return schedule_text

        #  Line info 
        # ← NEW: was falling through to str(info_data)
        if info_target == "line_info":
            line_name = info_data.get("route_name", line_id)
            mode      = info_data.get("mode", "?")
            operator  = info_data.get("operator", "?")
            cost      = info_data.get("cost_baseline")
            trips     = info_data.get("trips", [])

            result = _t(language, "line_info_header").format(line_name=line_name)
            result += _t(language, "line_info_mode").format(mode=mode)

            if operator and operator != "?":
                result += _t(language, "line_info_operator").format(operator=operator)
            if cost is not None:
                result += _t(language, "line_info_fare").format(
                    fare=f"{float(cost):.0f}"
                )
            if trips:
                result += _t(language, "line_info_trips").format(n=len(trips))

            # Show first trip's stop list if available
            if trips and trips[0].get("stops"):
                first_trip  = trips[0]
                stops       = first_trip["stops"]
                first_stop  = stops[0].get("stop_name_ar") or stops[0].get("stop_name", "?")
                last_stop   = stops[-1].get("stop_name_ar") or stops[-1].get("stop_name", "?")
                if language == Language.ARABIC:
                    result += f"من: {first_stop} لـ{last_stop}\n"
                else:
                    result += f"From: {first_stop} to {last_stop}\n"

            return result

        #  Unknown info target (shouldn't reach here after router validation) 
        logger.warning(
            "unknown_info_target_in_response_builder",
            info_target=info_target,
        )
        return _t(language, "info_not_found").format(
            target=info_target,
            line_id=line_id,
        )

    #  Error messages & prompts 

    def ask_missing(
        self,
        missing_fields: List[str],
        language:       Language = Language.ARABIC,
    ) -> str:
        """Ask user for missing origin/destination."""
        has_origin = "origin"      in missing_fields
        has_dest   = "destination" in missing_fields

        if has_origin and has_dest:
            return _t(language, "ask_both")
        elif has_origin:
            return _t(language, "ask_origin")
        elif has_dest:
            return _t(language, "ask_destination")
        return _t(language, "clarify")

    def stop_not_found(
        self,
        stop_name: str,
        language:  Language = Language.ARABIC,
    ) -> str:
        return _t(language, "stop_not_found").format(stop=stop_name)

    def no_route_found(
        self,
        origin:      str,
        destination: str,
        language:    Language = Language.ARABIC,
    ) -> str:
        return _t(language, "no_route").format(
            origin=origin,
            destination=destination,
        )

    def no_more_results(self, language: Language = Language.ARABIC) -> str:
        return _t(language, "no_more")

    def no_context(self, language: Language = Language.ARABIC) -> str:
        return _t(language, "no_context")

    def clarify(self, language: Language = Language.ARABIC) -> str:
        return _t(language, "clarify")

    def api_error(self, language: Language = Language.ARABIC) -> str:
        return _t(language, "api_error")

    def all_filtered(self, language: Language = Language.ARABIC) -> str:
        return _t(language, "all_filtered")