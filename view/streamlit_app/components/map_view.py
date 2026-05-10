"""
map_view.py
Route map visualization using Folium + streamlit-folium.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import folium
import streamlit as st

try:
    from streamlit_folium import st_folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


MODE_COLORS = {
    "metro":    "#E74C3C",
    "bus":      "#2E86C1",
    "microbus": "#8E44AD",
    "tram":     "#F39C12",
    "walk":     "#27AE60",
}


def render_map(journeys: List[Dict[str, Any]], selected_idx: int = 0) -> None:
    """
    Render a Folium map showing the selected journey route.

    Args:
        journeys:     List of display-ready journey dicts
        selected_idx: Which journey to show on the map
    """
    if not FOLIUM_AVAILABLE:
        st.info("📦 Install `streamlit-folium` for map view: `pip install streamlit-folium folium`")
        return

    if not journeys:
        return

    journey = journeys[selected_idx]
    steps   = journey.get("steps", [])

    if not steps:
        st.info("🗺️ Route map not available (no step coordinates)")
        return

    # ── Build map centered on origin ─────────────────────────────────────────
    origin_lat = journey.get("origin_lat")
    origin_lng = journey.get("origin_lng")

    if not origin_lat or not origin_lng:
        # Fallback: center on Alexandria Egypt
        origin_lat, origin_lng = 31.2001, 29.9187

    m = folium.Map(
        location=[origin_lat, origin_lng],
        zoom_start=13,
        tiles="CartoDB dark_matter",
    )

    # ── Origin marker ─────────────────────────────────────────────────────────
    folium.Marker(
        location=[origin_lat, origin_lng],
        popup="🟢 Origin",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(m)

    # ── Destination marker ────────────────────────────────────────────────────
    dest_lat = journey.get("dest_lat")
    dest_lng = journey.get("dest_lng")
    if dest_lat and dest_lng:
        folium.Marker(
            location=[dest_lat, dest_lng],
            popup="🔴 Destination",
            icon=folium.Icon(color="red", icon="flag", prefix="fa"),
        ).add_to(m)

    # ── Step stop markers + polylines ────────────────────────────────────────
    all_points = []

    for step in steps:
        mode  = step.get("mode", "bus")
        color = MODE_COLORS.get(mode, "#2E86C1")

        # Stop markers (if coordinates available)
        from_lat = step.get("from_lat")
        from_lng = step.get("from_lng")
        to_lat   = step.get("to_lat")
        to_lng   = step.get("to_lng")

        if from_lat and from_lng:
            all_points.append([from_lat, from_lng])
            folium.CircleMarker(
                location=[from_lat, from_lng],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.8,
                popup=step.get("from_stop_name", "Stop"),
            ).add_to(m)

        if to_lat and to_lng:
            all_points.append([to_lat, to_lng])
            folium.CircleMarker(
                location=[to_lat, to_lng],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.8,
                popup=step.get("to_stop_name", "Stop"),
            ).add_to(m)

            # Polyline between from → to
            if from_lat and from_lng:
                folium.PolyLine(
                    locations=[
                        [from_lat, from_lng],
                        [to_lat, to_lng],
                    ],
                    color=color,
                    weight=4,
                    opacity=0.8,
                    tooltip=step.get("line_name", mode.title()),
                    dash_array="5" if mode == "walk" else None,
                ).add_to(m)

    # ── Fit bounds if we have points ─────────────────────────────────────────
    if len(all_points) >= 2:
        m.fit_bounds(all_points)

    # ── Render ────────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="map-container">',
        unsafe_allow_html=True,
    )
    st_folium(m, width=None, height=300, returned_objects=[])
    st.markdown("</div>", unsafe_allow_html=True)