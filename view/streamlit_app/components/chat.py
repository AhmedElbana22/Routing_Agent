"""
chat.py
Chat window and message rendering component.
"""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st


def render_welcome_screen() -> None:
    """Render welcome screen shown before first message."""
    st.markdown("""
    <div class="welcome-card">
        <div class="welcome-icon">🚌</div>
        <div class="welcome-title">أهلاً بيك ,اسأل الاسطي</div>
        <div class="welcome-title" style="font-size:18px;margin-top:4px;">
            Welcome to OSTA - Your Alexandria Transport Assistant
        </div>
        <div class="welcome-subtitle" style="margin-top:16px;">
            I can help you find the best public transport routes in Alexandria.<br>
            Ask me in <strong>Arabic</strong>, <strong>English</strong>, or <strong>Mixed</strong>.
        </div>
        <div style="
            display:flex;
            gap:12px;
            justify-content:center;
            flex-wrap:wrap;
            margin-top:24px;
        ">
            <span style="
                background:rgba(46,134,193,0.2);
                border:1px solid rgba(46,134,193,0.4);
                border-radius:20px;
                padding:6px 16px;
                font-size:12px;
                color:#2E86C1;
            ">🗺️ Find Routes</span>
            <span style="
                background:rgba(243,156,18,0.2);
                border:1px solid rgba(243,156,18,0.4);
                border-radius:20px;
                padding:6px 16px;
                font-size:12px;
                color:#F39C12;
            ">💰 Compare Fares</span>
            <span style="
                background:rgba(39,174,96,0.2);
                border:1px solid rgba(39,174,96,0.4);
                border-radius:20px;
                padding:6px 16px;
                font-size:12px;
                color:#27AE60;
            ">⚡ Optimize Journey</span>
            <span style="
                background:rgba(142,68,173,0.2);
                border:1px solid rgba(142,68,173,0.4);
                border-radius:20px;
                padding:6px 16px;
                font-size:12px;
                color:#8E44AD;
            ">🔄 Follow-up Questions</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_message(role: str, content: str, turn_id: int = 0) -> None:
    """
    Render a single chat message bubble.

    Args:
        role:    "user" or "assistant"
        content: Message text
    """
    is_user    = role == "user"
    avatar     = "👤" if is_user else "🚌"
    bubble_cls = "user" if is_user else "bot"
    wrapper_cls = "user" if is_user else "bot"

    # Detect Arabic text for RTL support
    has_arabic = any('\u0600' <= c <= '\u06FF' for c in content)
    text_dir   = 'rtl' if has_arabic else 'ltr'
    text_align = 'right' if has_arabic else 'left'
    font_fam   = "'Alexandria', 'Inter', sans-serif" if has_arabic else "'Inter', sans-serif"

    st.markdown(f"""
    <div class="message-wrapper {wrapper_cls}">
        <div class="avatar {bubble_cls}">{avatar}</div>
        <div class="bubble {bubble_cls}" style="
            direction:{text_dir};
            text-align:{text_align};
            font-family:{font_fam};
        ">
            {content.replace(chr(10), "<br>")}
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_typing_indicator() -> None:
    """Show animated typing indicator while waiting for response."""
    st.markdown("""
    <div class="message-wrapper bot">
        <div class="avatar bot">🚌</div>
        <div class="bubble bot">
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_chat_history(messages: List[Dict[str, str]]) -> None:
    """Render full chat history."""
    for i, msg in enumerate(messages):
        render_message(
            role=msg["role"],
            content=msg["content"],
            turn_id=i,
        )