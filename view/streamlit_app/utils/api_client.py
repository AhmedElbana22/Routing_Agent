"""
api_client.py
HTTP client that calls the FastAPI backend.
Handles connection errors gracefully.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
import streamlit as st
 
BACKEND_URL = "http://localhost:5000"
TIMEOUT     = 30


def _post(endpoint: str, payload: dict) -> Optional[Dict[str, Any]]:
    """Generic POST with error handling."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(f"{BACKEND_URL}{endpoint}", json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        st.error("❌ Cannot connect to backend. Make sure `python main.py` is running.")
        return None
    except httpx.TimeoutException:
        st.error("⏱️ Request timed out. The server is taking too long.")
        return None
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        return None


def _get(endpoint: str, params: dict = None) -> Optional[Any]:
    """Generic GET with error handling."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(f"{BACKEND_URL}{endpoint}", params=params or {})
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        return None
    except Exception:
        return None


def send_message(message: str, session_id: str) -> Optional[Dict[str, Any]]:
    """Send a chat message to the agent."""
    return _post("/chat", {
        "message":    message,
        "session_id": session_id,
    })


def clear_session(session_id: str) -> bool:
    """Clear conversation memory for a session."""
    try:
        with httpx.Client(timeout=10) as client:
            r = client.delete(f"{BACKEND_URL}/session/{session_id}")
            return r.status_code == 200
    except Exception:
        return False


def get_stop_suggestions(query: str) -> List[str]:
    """Get stop name autocomplete suggestions."""
    result = _get("/suggest", {"q": query, "limit": 5})
    if result and isinstance(result, dict):
        return result.get("suggestions", [])
    return []


def health_check() -> bool:
    """Check if backend is running."""
    result = _get("/health")
    return result is not None and result.get("status") == "ok"


def get_active_sessions() -> int:
    """Get number of active sessions from health endpoint."""
    result = _get("/health")
    if result:
        return result.get("active_sessions", 0)
    return 0