"""
seed_examples.py
Raw hand-crafted seed examples for training data.
These are the ground-truth examples the model learns from.
Covers all query types, both languages, edge cases.
"""

from typing import List, Dict, Any

# Format
# Each example: {"text": str, "intent": dict}

SEED_EXAMPLES: List[Dict[str, Any]] = [
    # Type 1: Basic Journey Request (Arabic)
    {
        "text": "عايز أروح من سيدي بشر للمعمورة",
        "intent": {
            "query_type": "journey_request",
            "origin": "سيدي بشر",
            "destination": "المعمورة",
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "ازاي أوصل من العصافرة لعذبة سعد",
        "intent": {
            "query_type": "journey_request",
            "origin": "العصافرة",
            "destination": "عذبة سعد",
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "محتاج أروح من سيدي جابر لسان استيفانو",
        "intent": {
            "query_type": "journey_request",
            "origin": "سيدي جابر",
            "destination": "سان استيفانو",
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    # Type 1: Basic Journey Request (English) 
    {
        "text": "How do I get from Borg Al-Arab Old Terminal to Al-Masaken?",
        "intent": {
            "query_type": "journey_request",
            "origin": "Borg Al-Arab Old Terminal",
            "destination": "Al-Masaken",
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "en",
        },
    },
    {
        "text": "I want to go from Hanuvil Market to Agamy School",
        "intent": {
            "query_type": "journey_request",
            "origin": "Hanuvil Market",
            "destination": "Agamy School",
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "en",
        },
    },
    # Type 1: Mixed Language  
    {
        "text": "عايز أروح من Asafra Station للـ Abu Qir Station",
        "intent": {
            "query_type": "journey_request",
            "origin": "Asafra Station",
            "destination": "Abu Qir Station",
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    # Type 2: Optimize Time (Arabic)  
    {
        "text": "أسرع طريقة من ابوقير للمندرة",
        "intent": {
            "query_type": "journey_request",
            "origin": "ابوقير",
            "destination": "المندرة",
            "optimization": "min_time",
            "weights": {"cost": 0.05, "time": 0.90, "transfers": 0.03, "walking": 0.02},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "عايز أوصل بأسرع وقت ممكن من العصافرة لسيدي جابر",
        "intent": {
            "query_type": "journey_request",
            "origin": "العصافرة",
            "destination": "سيدي جابر",
            "optimization": "min_time",
            "weights": {"cost": 0.05, "time": 0.90, "transfers": 0.03, "walking": 0.02},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    # Type 2: Optimize Time (English) 
    {
        "text": "fastest route from Raml Station to Ber Masoud",
        "intent": {
            "query_type": "journey_request",
            "origin": "Raml Station",
            "destination": "Ber Masoud",
            "optimization": "min_time",
            "weights": {"cost": 0.05, "time": 0.90, "transfers": 0.03, "walking": 0.02},
            "constraints": [],
            "also_report": [],
            "language": "en",
        },
    },
    # Type 3: Optimize Cost  
    {
        "text": "أرخص طريقة من ميدان الساعة لشارع القاهرة",
        "intent": {
            "query_type": "journey_request",
            "origin": "ميدان الساعة",
            "destination": "شارع القاهرة",
            "optimization": "min_cost",
            "weights": {"cost": 0.90, "time": 0.05, "transfers": 0.03, "walking": 0.02},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "cheapest way from Jewelery Museum to Bakus",
        "intent": {
            "query_type": "journey_request",
            "origin": "Jewelery Museum",
            "destination": "Bakus",
            "optimization": "min_cost",
            "weights": {"cost": 0.90, "time": 0.05, "transfers": 0.03, "walking": 0.02},
            "constraints": [],
            "also_report": [],
            "language": "en",
        },
    },
    # Type 4: Optimize Transfers  
    {
        "text": "عايز أروح بأقل تحويلات من ميدان الساعة للعجمي",
        "intent": {
            "query_type": "journey_request",
            "origin": "ميدان الساعة",
            "destination": "العجمي",
            "optimization": "min_transfers",
            "weights": {"cost": 0.05, "time": 0.10, "transfers": 0.80, "walking": 0.05},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "minimum transfers from El Saah Square to Karmus",
        "intent": {
            "query_type": "journey_request",
            "origin": "El Saah Square",
            "destination": "Karmus",
            "optimization": "min_transfers",
            "weights": {"cost": 0.05, "time": 0.10, "transfers": 0.80, "walking": 0.05},
            "constraints": [],
            "also_report": [],
            "language": "en",
        },
    },
    # Type 5: Compound Informational   
    {
        "text": "أقل تحويلات وكمان عايز أعرف التمن",
        "intent": {
            "query_type": "journey_request",
            "origin": None,
            "destination": None,
            "optimization": "min_transfers",
            "weights": {"cost": 0.15, "time": 0.05, "transfers": 0.75, "walking": 0.05},
            "constraints": [],
            "also_report": ["fare"],
            "language": "ar",
        },
    },
    # Type 6: Balanced  
    {
        "text": "عايز حاجة معقولة مش بالضرورة أسرع أو أرخص",
        "intent": {
            "query_type": "journey_request",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    #  Type 7: Constrained  
    {
        "text": "أسرع طريقة من سيدي بشر لعذبة سعد بس مش أكتر من 20 جنيه",
        "intent": {
            "query_type": "journey_request",
            "origin": "سيدي بشر",
            "destination": "عذبة سعد",
            "optimization": "min_time",
            "weights": {"cost": 0.15, "time": 0.70, "transfers": 0.10, "walking": 0.05},
            "constraints": [{"field": "fare", "operator": "lte", "value": 20.0}],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "fastest route from Al Seyouf to Abu Qir Station but max 15 EGP",
        "intent": {
            "query_type": "journey_request",
            "origin": "Al Seyouf",
            "destination": "Abu Qir Station",
            "optimization": "min_time",
            "weights": {"cost": 0.15, "time": 0.70, "transfers": 0.10, "walking": 0.05},
            "constraints": [{"field": "fare", "operator": "lte", "value": 15.0}],
            "also_report": [],
            "language": "en",
        },
    },
    {
        "text": "أرخص طريقة بس مش أكتر من ساعة",
        "intent": {
            "query_type": "journey_request",
            "origin": None,
            "destination": None,
            "optimization": "min_cost",
            "weights": {"cost": 0.70, "time": 0.15, "transfers": 0.10, "walking": 0.05},
            "constraints": [{"field": "duration", "operator": "lte", "value": 60.0}],
            "also_report": [],
            "language": "ar",
        },
    },
    # Follow-ups 
    {
        "text": "طب وإيه لو أسرع طريقة؟",
        "intent": {
            "query_type": "followup",
            "origin": None,
            "destination": None,
            "optimization": "min_time",
            "weights": {"cost": 0.05, "time": 0.90, "transfers": 0.03, "walking": 0.02},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "what if I want the cheapest instead?",
        "intent": {
            "query_type": "followup",
            "origin": None,
            "destination": None,
            "optimization": "min_cost",
            "weights": {"cost": 0.90, "time": 0.05, "transfers": 0.03, "walking": 0.02},
            "constraints": [],
            "also_report": [],
            "language": "en",
        },
    },
    {
        "text": "وإيه لو مفيش تحويلات خالص؟",
        "intent": {
            "query_type": "followup",
            "origin": None,
            "destination": None,
            "optimization": "min_transfers",
            "weights": {"cost": 0.05, "time": 0.10, "transfers": 0.80, "walking": 0.05},
            "constraints": [{"field": "transfers", "operator": "eq", "value": 0.0}],
            "also_report": [],
            "language": "ar",
        },
    },
    # Show More / Pagination  
    {
        "text": "وريني خيارات تانية",
        "intent": {
            "query_type": "show_more",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
        },
    },
    {
        "text": "show me more options",
        "intent": {
            "query_type": "show_more",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "en",
        },
    },
    # Show Detail 
    {
        "text": "فيه تفاصيل أكتر عن الأول؟",
        "intent": {
            "query_type": "show_detail",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
            "result_index": 0,
        },
    },
    {
        "text": "tell me more about option 2",
        "intent": {
            "query_type": "show_detail",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "en",
            "result_index": 1,
        },
    },
    # Info Requests  
    {
        "text": "كام تعريفة خط 72؟",
        "intent": {
            "query_type": "info_request",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
            "info_target": "fare",
            "info_params": {"line_id": "72"},
        },
    },
    {
        "text": "what is the fare of metro line 1?",
        "intent": {
            "query_type": "info_request",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "en",
            "info_target": "fare",
            "info_params": {"line_id": "metro_1"},
        },
    },
    {
        "text": "مواعيد الأتوبيس 55 فين؟",
        "intent": {
            "query_type": "info_request",
            "origin": None,
            "destination": None,
            "optimization": "balanced",
            "weights": {"cost": 0.25, "time": 0.25, "transfers": 0.25, "walking": 0.25},
            "constraints": [],
            "also_report": [],
            "language": "ar",
            "info_target": "schedule",
            "info_params": {"line_id": "55"},
        },
    },
]