"""
journey_card.py
Renders a single journey result card.
"""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from view.streamlit_app.utils.formatters import MODE_ICONS, MODE_COLORS


def render_mode_pills(mode_sequence: List[Dict[str, str]]) -> str:
    """Build HTML for transport mode pills."""
    pills = []
    for i, item in enumerate(mode_sequence):
        mode  = item.get("mode", "bus")
        icon  = item.get("icon", "🚌")
        name  = item.get("name", mode.title())
        color = MODE_COLORS.get(mode, "#2E86C1")

        pill = (
            f'<span class="mode-pill {mode}">'
            f'{icon} {name}'
            f'</span>'
        )
        pills.append(pill)

        # Arrow between steps
        if i < len(mode_sequence) - 1:
            pills.append(
                '<span style="color:#718096;font-size:10px;margin:0 4px;">▶</span>'
            )

    return "".join(pills)


def render_journey_card(
    journey: Dict[str, Any],
    index: int,
    on_detail_click: bool = True,
) -> bool:
    """
    Render a single journey card.
    Returns True if detail button was clicked.
    """
    rank         = journey["rank"]
    is_best      = rank == 1
    card_class   = f"journey-card {'rank-1' if is_best else ''}"
    detail_key   = f"detail_btn_{index}_{journey['journey_id']}"

    st.markdown(f"""
    <div class="{card_class}">

        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
            <div style="display:flex;align-items:center;gap:12px;">
                <span class="journey-rank">#{rank}</span>
                <div>
                    <div style="font-weight:600;font-size:15px;color:#FAFAFA;">
                        {journey["line_summary"]}
                    </div>
                    <div style="margin-top:6px;">
                        {render_mode_pills(journey["mode_sequence"])}
                    </div>
                </div>
            </div>
        </div>

        <div class="journey-stats">
            <div class="stat-badge">
                <span class="icon">⏱</span>
                <span>{journey["duration_str"]}</span>
            </div>
            <div class="stat-badge">
                <span class="icon">💰</span>
                <span>{journey["fare_str"]}</span>
            </div>
            <div class="stat-badge">
                <span class="icon">🔄</span>
                <span>{journey["transfers"]} transfer{"s" if journey["transfers"] != 1 else ""}</span>
            </div>
            <div class="stat-badge">
                <span class="icon">🚶</span>
                <span>{journey["walking_str"]}</span>
            </div>
        </div>

        {f'<div class="journey-reason">📍 {journey["rank_reason"]}</div>' if journey["rank_reason"] else ""}

    </div>
    """, unsafe_allow_html=True)

    # Detail button
    clicked = False
    if on_detail_click:
        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("Details →", key=detail_key, use_container_width=True):
                clicked = True

    return clicked


def render_journey_detail(journey: Dict[str, Any]) -> None:
    """
    Render full detail view for a journey.
    Shown in an expander or modal.
    """
    steps = journey.get("steps", [])

    st.markdown(f"""
    <div style="
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 24px;
        margin: 16px 0;
    ">
        <div style="font-size:18px;font-weight:700;color:#FAFAFA;margin-bottom:16px;">
            🗺️ Journey #{journey["rank"]} — Full Details
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Stats row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("⏱ Duration",  journey["duration_str"])
    with col2:
        st.metric("💰 Fare",      journey["fare_str"])
    with col3:
        st.metric("🔄 Transfers", str(journey["transfers"]))
    with col4:
        st.metric("🚶 Walking",   journey["walking_str"])

    # Steps timeline
    if steps:
        st.markdown("### Step-by-Step")
        for i, step in enumerate(steps, 1):
            mode      = step.get("mode", "bus")
            icon      = MODE_ICONS.get(mode, "🚌")
            line      = step.get("line_name") or f"Line {step.get('line_id', '?')}"
            from_stop = step.get("from_stop_name", "")
            to_stop   = step.get("to_stop_name", "")
            duration  = step.get("duration_minutes", 0)
            fare      = step.get("fare_egp", 0)

            color = MODE_COLORS.get(mode, "#2E86C1")

            st.markdown(f"""
            <div style="
                display:flex;
                gap:16px;
                padding:12px 0;
                border-bottom:1px solid rgba(255,255,255,0.05);
            ">
                <div style="
                    width:36px;height:36px;
                    border-radius:50%;
                    background:{color}22;
                    border:2px solid {color};
                    display:flex;align-items:center;
                    justify-content:center;
                    font-size:18px;
                    flex-shrink:0;
                ">{icon}</div>
                <div style="flex:1;">
                    <div style="font-weight:600;font-size:13px;color:#FAFAFA;">
                        {i}. {line if mode != "walk" else "Walk"}
                    </div>
                    <div style="font-size:12px;color:#A0AEC0;margin-top:2px;">
                        {from_stop} → {to_stop}
                    </div>
                    <div style="
                        display:flex;gap:12px;
                        margin-top:6px;font-size:11px;color:#718096;
                    ">
                        <span>⏱ {int(duration)} min</span>
                        {"<span>💰 " + str(int(fare)) + " EGP</span>" if fare > 0 else ""}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # Ranking info
    if journey.get("rank_reason"):
        st.info(f"📍 **Why ranked #{journey['rank']}:** {journey['rank_reason']}")