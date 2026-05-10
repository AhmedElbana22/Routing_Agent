"""
app.py
Main Streamlit application entry point.

Run: streamlit run view/streamlit_app/app.py

Architecture:
  - Sidebar:     examples + settings + session control
  - Main area:   chat window + journey cards + map
  - State:       Streamlit session_state for memory
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

# ── Page configuration (MUST be first Streamlit call) ────────────────────────
st.set_page_config(
    page_title="OSTA - Your Alexandria Transport Assistant",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Load CSS ──────────────────────────────────────────────────────────────────
CSS_PATH = Path(__file__).parent / "styles" / "main.css"

def load_css() -> None:
    if CSS_PATH.exists():
        with open(CSS_PATH, encoding="utf-8", errors="replace") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css()

# ── Imports (after path setup) ────────────────────────────────────────────────
from view.streamlit_app.components.chat       import (
    render_welcome_screen,
    render_message,
    render_typing_indicator,
    render_chat_history,
)
from view.streamlit_app.components.journey_card import (
    render_journey_card,
    render_journey_detail,
)
from view.streamlit_app.components.sidebar     import render_sidebar
from view.streamlit_app.components.map_view    import render_map
from view.streamlit_app.utils.api_client       import send_message, health_check
from view.streamlit_app.utils.formatters       import journey_to_display


# ═════════════════════════════════════════════════════════════════════════════
# Session State Initialization
# ═════════════════════════════════════════════════════════════════════════════

def init_session_state() -> None:
    """Initialize all session state variables."""
    defaults = {
        "session_id":       str(uuid.uuid4()),
        "messages":         [],          # chat history
        "journey_results":  [],          # latest journey display data
        "has_more":         False,
        "turn_count":       0,
        "show_debug":       False,
        "show_map":         True,
        "auto_details":     False,
        "selected_journey": None,        # for detail view
        "show_detail":      False,
        "prefill_input":    "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session_state()


# ═════════════════════════════════════════════════════════════════════════════
# Header Component
# ═════════════════════════════════════════════════════════════════════════════

def render_header() -> None:
    """Render the application header."""
    is_online = health_check()
    status    = "🟢 Online" if is_online else "🔴 Offline"

    st.markdown(f"""
    <div class="app-header">
        <div>
            <div style="display:flex;align-items:center;gap:12px;">
                <span style="font-size:40px;">🚌</span>
                <div>
                    <p class="app-header-title">الاسطي معاك</p>
                    <p class="app-header-subtitle">OSTA - Your Alexandria Transport Assistant — Find the best routes</p>
                </div>
            </div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
            <span class="app-header-badge">{status}</span>
            <span class="app-header-badge" style="background:rgba(255,255,255,0.1);">
                🆔 {st.session_state["session_id"][:8]}...
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# Journey Results Panel
# ═════════════════════════════════════════════════════════════════════════════

def render_journey_panel() -> None:
    """Render the journey results panel (right column)."""
    journeys = st.session_state["journey_results"]

    if not journeys:
        st.markdown("""
        <div style="
            text-align:center;
            padding:60px 20px;
            color:#4A5568;
        ">
            <div style="font-size:48px;margin-bottom:16px;">🗺️</div>
            <div style="font-size:14px;">
                Journey results will appear here
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── Results header ────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="
        display:flex;
        align-items:center;
        justify-content:space-between;
        margin-bottom:16px;
    ">
        <div style="font-size:16px;font-weight:700;color:#FAFAFA;">
            🗺️ Found {len(journeys)} Route{"s" if len(journeys) != 1 else ""}
        </div>
        {"<div style='font-size:12px;color:#F39C12;'>More available ↓</div>" if st.session_state["has_more"] else ""}
    </div>
    """, unsafe_allow_html=True)

    # ── Map view ──────────────────────────────────────────────────────────────
    if st.session_state.get("show_map", True) and journeys:
        with st.expander("🗺️ Route Map", expanded=True):
            if len(journeys) > 1:
                map_options = [f"Route #{j['rank']}" for j in journeys]
                selected_map = st.selectbox(
                    "Show route:",
                    map_options,
                    key="map_select",
                    label_visibility="collapsed",
                )
                selected_idx = map_options.index(selected_map)
            else:
                selected_idx = 0
            render_map(journeys, selected_idx)

    # ── Journey cards ─────────────────────────────────────────────────────────
    for i, journey in enumerate(journeys):
        detail_clicked = render_journey_card(
            journey=journey,
            index=i,
            on_detail_click=True,
        )
        if detail_clicked:
            st.session_state["selected_journey"] = i
            st.session_state["show_detail"] = True

    # ── Detail modal ──────────────────────────────────────────────────────────
    if (
        st.session_state["show_detail"]
        and st.session_state["selected_journey"] is not None
    ):
        idx     = st.session_state["selected_journey"]
        journey = journeys[idx] if idx < len(journeys) else None

        if journey:
            with st.expander(
                f"📋 Journey #{journey['rank']} — Full Details",
                expanded=True,
            ):
                render_journey_detail(journey)
                if st.button("✕ Close Details", key="close_detail"):
                    st.session_state["show_detail"] = False
                    st.rerun()

    # ── Show more button ──────────────────────────────────────────────────────
    if st.session_state["has_more"]:
        st.markdown('<div style="margin-top:12px;">', unsafe_allow_html=True)
        if st.button(
            "🔄 Show More Options / وريني أكتر",
            use_container_width=True,
            key="show_more_btn",
        ):
            _send_and_update("وريني أكتر")
        st.markdown("</div>", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# Stats Bar
# ═════════════════════════════════════════════════════════════════════════════

def render_stats_bar() -> None:
    """Render quick stats from latest journey results."""
    journeys = st.session_state["journey_results"]
    if not journeys:
        return

    best = journeys[0]
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">⏱ {best["duration_str"]}</div>
            <div class="metric-label">Best Duration</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">💰 {best["fare_str"]}</div>
            <div class="metric-label">Best Fare</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">🔄 {best["transfers"]}</div>
            <div class="metric-label">Min Transfers</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-value">🗺️ {len(journeys)}</div>
            <div class="metric-label">Routes Found</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div style="margin-bottom:16px;"></div>', unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# Core: Send message and update state
# ═════════════════════════════════════════════════════════════════════════════

def _send_and_update(user_input: str) -> None:
    """
    Send message to agent, update all session state.
    This is the core function that connects UI → backend.
    """
    user_input = user_input.strip()
    if not user_input:
        return

    # Add user message to history
    st.session_state["messages"].append({
        "role":    "user",
        "content": user_input,
    })

    # Call backend
    response = send_message(
        message=user_input,
        session_id=st.session_state["session_id"],
    )

    if response is None:
        # Backend error already shown by api_client
        st.session_state["messages"].append({
            "role":    "assistant",
            "content": "❌ Could not reach the server. Please try again.",
        })
        return

    # ── Extract response text ─────────────────────────────────────────────────
    agent_text = response.get("text", "")
    has_more   = response.get("has_more", False)
    raw_journeys = response.get("journeys", [])
    turn_id    = response.get("turn_id", 0)
    error      = response.get("error")

    # ── Add agent message to history ──────────────────────────────────────────
    st.session_state["messages"].append({
        "role":    "assistant",
        "content": agent_text,
    })

    # ── Update journey results ────────────────────────────────────────────────
    if raw_journeys:
        st.session_state["journey_results"] = [
            journey_to_display(j) for j in raw_journeys
        ]
        st.session_state["show_detail"] = False
        st.session_state["selected_journey"] = None

    st.session_state["has_more"]   = has_more
    st.session_state["turn_count"] = turn_id

    # ── Debug info ────────────────────────────────────────────────────────────
    if st.session_state.get("show_debug") and response.get("intent"):
        intent = response["intent"]
        st.session_state["last_intent"] = intent

    if error:
        st.warning(f"⚠️ Agent warning: {error}")


# ═════════════════════════════════════════════════════════════════════════════
# Debug Panel
# ═════════════════════════════════════════════════════════════════════════════

def render_debug_panel() -> None:
    """Render debug info panel — shown only when debug toggle is ON."""
    if not st.session_state.get("show_debug"):
        return

    intent = st.session_state.get("last_intent")
    if not intent:
        return

    with st.expander("🔍 Debug — Last Intent", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Parsed Intent**")
            st.json({
                "query_type":   intent.get("query_type"),
                "origin":       intent.get("origin"),
                "destination":  intent.get("destination"),
                "optimization": intent.get("optimization"),
                "language":     intent.get("language"),
                "confidence":   intent.get("confidence"),
            })

        with col2:
            st.markdown("**Weights**")
            weights = intent.get("weights", {})
            if weights:
                import pandas as pd
                df = pd.DataFrame([{
                    "Dimension": k.title(),
                    "Weight":    round(v, 3),
                } for k, v in weights.items()])

                st.bar_chart(
                    df.set_index("Dimension"),
                    use_container_width=True,
                    height=150,
                )

            if intent.get("constraints"):
                st.markdown("**Constraints**")
                for c in intent["constraints"]:
                    st.markdown(
                        f'<span style="'
                        f'background:rgba(231,76,60,0.2);'
                        f'border:1px solid rgba(231,76,60,0.4);'
                        f'border-radius:6px;padding:4px 10px;'
                        f'font-size:12px;color:#E74C3C;">'
                        f'{c["field"]} {c["operator"]} {c["value"]}'
                        f'</span>',
                        unsafe_allow_html=True,
                    )


# ═════════════════════════════════════════════════════════════════════════════
# Input Component
# ═════════════════════════════════════════════════════════════════════════════

def render_input_area(prefill: str = "") -> None:
    """
    Render the message input area with send button.
    Handles prefill from sidebar examples.
    """
    st.markdown(
        '<div class="input-container">',
        unsafe_allow_html=True,
    )

    col_input, col_send = st.columns([5, 1])

    with col_input:
        user_input = st.text_input(
            label="Message",
            value=prefill,
            placeholder="اكتب سؤالك هنا... / Type your question here...",
            key="chat_input",
            label_visibility="collapsed",
        )

    with col_send:
        send_clicked = st.button(
            "Send ➤",
            type="primary",
            use_container_width=True,
            key="send_btn",
        )

    # ── Quick action buttons ──────────────────────────────────────────────────
    st.markdown(
        '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">',
        unsafe_allow_html=True,
    )

    quick_actions = [
        ("🔄 Re-rank: Fastest",    "أسرع طريقة"),
        ("💰 Re-rank: Cheapest",   "أرخص طريقة"),
        ("🚶 Min Transfers",       "أقل تحويلات"),
        ("➕ Show More",           "وريني أكتر"),
        ("📋 Detail #1",           "تفاصيل الأول"),
    ]

    cols = st.columns(len(quick_actions))
    for col, (label, action_text) in zip(cols, quick_actions):
        with col:
            if st.button(label, key=f"quick_{action_text}", use_container_width=True):
                _send_and_update(action_text)
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Handle send ───────────────────────────────────────────────────────────
    if (send_clicked or (user_input and user_input != prefill)) and user_input.strip():
        if send_clicked or st.session_state.get("_last_input") != user_input:
            st.session_state["_last_input"] = user_input
            _send_and_update(user_input)
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# Main Layout
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """
    Main app layout.

    Layout:
      ┌─────────────────────────────────────────────┐
      │              Header                          │
      ├─────────────────────────┬───────────────────┤
      │   Chat (left, 55%)      │  Results (right)  │
      │   - message history     │  - stats bar      │
      │   - input area          │  - journey cards  │
      │   - debug panel         │  - map view       │
      └─────────────────────────┴───────────────────┘
    """

    # ── Sidebar (returns prefill if example clicked) ──────────────────────────
    prefill = render_sidebar(st.session_state["session_id"])

    # ── Header ────────────────────────────────────────────────────────────────
    render_header()

    # ── Main columns ──────────────────────────────────────────────────────────
    chat_col, results_col = st.columns([55, 45], gap="large")

    # ════════════════════════════════════════════════
    # LEFT — Chat column
    # ════════════════════════════════════════════════
    with chat_col:
        st.markdown("""
        <div style="
            font-size:13px;
            font-weight:600;
            color:#718096;
            text-transform:uppercase;
            letter-spacing:1px;
            margin-bottom:12px;
        ">💬 Conversation</div>
        """, unsafe_allow_html=True)

        # ── Chat window ───────────────────────────────────────────────────────
        messages = st.session_state["messages"]

        # Chat scroll container
        chat_html_open = """
        <div class="chat-container" id="chat-window">
        """
        chat_html_close = "</div>"

        if not messages:
            render_welcome_screen()
        else:
            st.markdown(chat_html_open, unsafe_allow_html=True)

            # Render all messages
            for msg in messages:
                render_message(
                    role=msg["role"],
                    content=msg["content"],
                )

            st.markdown(chat_html_close, unsafe_allow_html=True)

            # Auto-scroll to bottom via JS
            st.markdown("""
            <script>
                const chatWindow = document.getElementById("chat-window");
                if (chatWindow) {
                    chatWindow.scrollTop = chatWindow.scrollHeight;
                }
            </script>
            """, unsafe_allow_html=True)

        # ── Turn counter ──────────────────────────────────────────────────────
        if st.session_state["turn_count"] > 0:
            st.markdown(f"""
            <div style="
                text-align:right;
                font-size:11px;
                color:#4A5568;
                margin-top:4px;
            ">Turn {st.session_state["turn_count"]}</div>
            """, unsafe_allow_html=True)

        # ── Input area ────────────────────────────────────────────────────────
        render_input_area(prefill=prefill or "")

        # ── Debug panel ───────────────────────────────────────────────────────
        render_debug_panel()

    # ════════════════════════════════════════════════
    # RIGHT — Results column
    # ════════════════════════════════════════════════
    with results_col:
        st.markdown("""
        <div style="
            font-size:13px;
            font-weight:600;
            color:#718096;
            text-transform:uppercase;
            letter-spacing:1px;
            margin-bottom:12px;
        ">🗺️ Journey Results</div>
        """, unsafe_allow_html=True)

        # Stats bar (only when results exist)
        render_stats_bar()

        # Journey cards + map
        render_journey_panel()


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()