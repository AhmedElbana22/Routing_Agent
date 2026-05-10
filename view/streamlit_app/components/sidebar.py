"""
sidebar.py
Sidebar component with examples, settings, and session info.
"""

from __future__ import annotations

from typing import Optional
import streamlit as st


EXAMPLE_QUERIES = {
    "🇪🇬 Arabic": [
        ("Basic Journey",     "عايز أروح من العوايد لسموحة"),
        ("Fastest",           "أسرع طريقة من سيدي بشر للحضرة"),
        ("Cheapest",          "أرخص طريقة من فيكتوريا لابوقير"),
        ("Min Transfers",     "أقل تحويلات من الساعة للمنتزه"),
        ("With Constraint",   "أسرع بس مش أكتر من 20 جنيه"),
        ("Show More",         "وريني أكتر"),
        ("Follow-up",         "طب وإيه لو أرخص؟"),
        ("Detail",            "تفاصيل الأول"),
        ("Line Fare",         "كام تعريفة خط 72؟"),
    ],
    "🇬🇧 English": [
        ("Basic Journey",     "I want to go from Awaid to Smoha"),
        ("Fastest",           "fastest route from Sidi Bishr to El Hadra"),
        ("Cheapest",          "cheapest way from Victoria to Abu Qir"),
        ("Min Transfers",     "minimum transfers from El Sa'a to Montazah"),
        ("With Constraint",   "fastest but max 15 EGP from El Agmy to Sidi Gaber"),
        ("Show More",         "show me more options"),
        ("Follow-up",         "what if I want the cheapest instead?"),
        ("Detail",            "tell me more about option 1"),
    ],
    "🔀 Mixed": [
        ("Mixed 1",           "عايز أروح من Smoha للـ Sidi Bishr"),
        ("Mixed 2",           "أسرع route من فيكتوريا لابوقير"),
        ("Mixed 3",           "show me أرخص option"),
    ],
}


def render_sidebar(session_id: str) -> Optional[str]:
    """
    Render the full sidebar.
    Returns a prefill text if an example was clicked, else None.
    """
    prefill = None

    with st.sidebar:
        # ── Logo & Branding ───────────────────────────────────────────────────
        st.markdown("""
        <div style="text-align:center;padding:20px 0 10px;">
            <div style="font-size:48px;">🚌</div>
            <div style="font-size:16px;font-weight:700;color:#FAFAFA;
                        font-family:'Alexandria',sans-serif;">
                مساعد المواصلات
            </div>
            <div style="font-size:11px;color:#718096;margin-top:4px;">
                OSTA - Your Alexandria Transport Assistant
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # ── Connection Status ─────────────────────────────────────────────────
        from view.streamlit_app.utils.api_client import health_check, get_active_sessions
        is_online = health_check()
        status_html = (
            '<span class="status-dot online"></span> Online'
            if is_online else
            '<span class="status-dot offline"></span> Offline'
        )
        active = get_active_sessions() if is_online else 0

        st.markdown(f"""
        <div class="sidebar-section">
            <div class="sidebar-section-title">System Status</div>
            <div style="font-size:13px;color:#A0AEC0;">{status_html}</div>
            <div style="font-size:11px;color:#718096;margin-top:6px;">
                Active sessions: {active}
            </div>
            <div style="font-size:11px;color:#718096;">
                Session: {session_id[:12]}...
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Example Queries ───────────────────────────────────────────────────
        st.markdown("""
        <div class="sidebar-section-title" style="
            margin-top:16px;
            font-size:11px;
            text-transform:uppercase;
            letter-spacing:1px;
            color:#718096;
            font-weight:600;
        ">💡 Try These Examples</div>
        """, unsafe_allow_html=True)

        for lang_label, examples in EXAMPLE_QUERIES.items():
            with st.expander(lang_label, expanded=(lang_label == "🇪🇬 Arabic")):
                for label, query_text in examples:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(
                            f'<div style="font-size:12px;color:#A0AEC0;'
                            f'padding:4px 0;font-family:Alexandria,sans-serif;">'
                            f'{query_text}</div>',
                            unsafe_allow_html=True,
                        )
                    with col2:
                        if st.button(
                            "Use",
                            key=f"ex_{lang_label}_{label}",
                            width='stretch',
                        ):
                            prefill = query_text

        st.divider()

        # ── Settings ──────────────────────────────────────────────────────────
        st.markdown("""
        <div class="sidebar-section-title" style="
            font-size:11px;
            text-transform:uppercase;
            letter-spacing:1px;
            color:#718096;
            font-weight:600;
        ">⚙️ Settings</div>
        """, unsafe_allow_html=True)

        show_debug = st.toggle(
            "Show Debug Info",
            value=False,
            key="show_debug",
        )
        if "show_map" not in st.session_state:
            st.session_state["show_map"] = True  # set default only once

        show_map = st.toggle("Show Map", key="show_map")
        show_details = st.toggle(
            "Auto-expand Details",
            value=False,
            key="auto_details",
        )

        # Widget keys manage their own session state; avoid reassigning here

        st.divider()

        # ── Clear Chat ────────────────────────────────────────────────────────
        if st.button(
            "🗑️ Clear Conversation",
            width='stretch',
            type="secondary",
        ):
            from view.streamlit_app.utils.api_client import clear_session
            clear_session(session_id)
            st.session_state["messages"] = []
            st.session_state["journey_results"] = []
            st.session_state["turn_count"] = 0
            st.rerun()

        st.markdown("""
        <div style="
            text-align:center;
            font-size:10px;
            color:#4A5568;
            margin-top:24px;
            padding-top:16px;
            border-top:1px solid rgba(255,255,255,0.05);
        ">
            Transport AI Agent v1.0<br>
            Graduation Project 2025
        </div>
        """, unsafe_allow_html=True)

    return prefill