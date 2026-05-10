"""
formatters.py
Format raw API response data for Streamlit display.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


MODE_ICONS = {
    "metro":    "🚇",
    "bus":      "🚌",
    "microbus": "🚐",
    "tram":     "🚃",
    "walk":     "🚶",
}

MODE_COLORS = {
    "metro":    "#E74C3C",
    "bus":      "#2E86C1",
    "microbus": "#8E44AD",
    "tram":     "#F39C12",
    "walk":     "#27AE60",
}


def format_duration(minutes: float) -> str:
    """45.5 → '45 min' | 90 → '1h 30min'"""
    mins = int(minutes)
    if mins >= 60:
        h = mins // 60
        m = mins % 60
        return f"{h}h {m}min" if m else f"{h}h"
    return f"{mins} min"


def format_fare(fare_egp: float) -> str:
    """12.5 → '12.50 EGP'"""
    return f"{fare_egp:.0f} EGP"


def format_walking(meters: float) -> str:
    """1500 → '1.5 km' | 800 → '800 m'"""
    if meters >= 1000:
        return f"{meters/1000:.1f} km"
    return f"{int(meters)} m"


def get_line_summary(steps: List[Dict]) -> str:
    """
    Build line summary from steps.
    [bus_72, walk, metro_1] → 'Bus 72 → Metro Line 1'
    """
    transit = [
        s for s in steps
        if s.get("mode", "walk") != "walk"
    ]
    if not transit:
        return "Direct Walk"
    parts = [s.get("line_name") or f"Line {s.get('line_id', '?')}" for s in transit]
    return " → ".join(parts)


def get_mode_sequence(steps: List[Dict]) -> List[Dict[str, str]]:
    """
    Extract ordered list of transport modes from steps.
    Returns [{"mode": "bus", "name": "Bus 72"}, ...]
    """
    result = []
    for step in steps:
        mode = step.get("mode", "walk")
        name = step.get("line_name") or MODE_ICONS.get(mode, "🚌")
        result.append({"mode": mode, "name": name, "icon": MODE_ICONS.get(mode, "🚌")})
    return result


def journey_to_display(journey: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert raw journey dict to display-ready dict.
    """
    steps = journey.get("steps", [])
    return {
        "rank":          journey.get("rank", 0),
        "journey_id":    journey.get("journey_id", ""),
        "duration_str":  format_duration(journey.get("total_duration_minutes", 0)),
        "fare_str":      format_fare(journey.get("total_fare_egp", 0)),
        "transfers":     journey.get("transfers", 0),
        "walking_str":   format_walking(journey.get("total_walking_meters", 0)),
        "line_summary":  get_line_summary(steps),
        "mode_sequence": get_mode_sequence(steps),
        "rank_reason":   journey.get("rank_reason", ""),
        "steps":         steps,
        "score":         journey.get("score", 0.0),
        "ranking_source": journey.get("ranking_source", "mnl"),
        # Raw values for map
        "origin_lat":    journey.get("origin_lat"),
        "origin_lng":    journey.get("origin_lng"),
        "dest_lat":      journey.get("destination_lat"),
        "dest_lng":      journey.get("destination_lng"),
        # Raw values for detail
        "raw_duration":  journey.get("total_duration_minutes", 0),
        "raw_fare":      journey.get("total_fare_egp", 0),
        "raw_walking":   journey.get("total_walking_meters", 0),
    }