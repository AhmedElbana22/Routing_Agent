"""
conversation.py — Conversation memory management for routing agent.

Stores journey results, intent history, and resolved coordinates
for follow-up resolution without repeated geo calls.

Key design decisions:
  - Stores lat/lon coordinates (not stop IDs) — matches routing API
  - resolve_intent() returns a COPY — never mutates shared objects
  - Cursor is advanced in save_turn() for journey turns (not just show_more)
  - detect_topic_shift() uses normalized text comparison
  - Persistent context only updated for journey-type turns
"""

# how it works : 
#1. ConversationMemory class maintains a sliding window of conversation turns, along with persistent context fields (origin/destination text, coordinates, optimization weights, language).
#2. Each turn is saved with save_turn(), which also updates persistent context and manages the display cursor for pagination.
#3. get_context() builds a MemoryContext snapshot for the controller, using cached journey lists that survive window sliding.
#4. resolve_intent() fills missing fields in a new Intent based on memory context, returning a COPY to avoid mutating shared objects.
#5. detect_topic_shift() compares normalized origin/destination text to detect meaningful changes.  
#6. SessionStore manages multiple ConversationMemory instances keyed by session_id, with TTL-based eviction and LRU overflow eviction.

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from model.intent.schema import (
    Coordinate,
    ConversationTurn,
    Intent,
    Journey,
    Language,
    MemoryContext,
    OptimizationGoal,
    QueryType,
    WeightVector,
)

import structlog

logger = structlog.get_logger(__name__)


#  Text normalizer import for topic shift comparison 
# Reuse same normalizer as geo_tool — consistent Arabic normalization
try:
    from controller.tools.geo_tool import TextNormalizer
except ImportError:
    # Fallback if geo_tool not importable (e.g. during tests)
    class TextNormalizer:  # type: ignore
        @staticmethod
        def normalize(text: str) -> str:
            return text.strip().lower()


class ConversationMemory:
    """
    Per-session sliding-window memory.

    Thread-safe (one lock per session).
    Maintains persistent fields across window slides:
      - origin / destination text
      - resolved lat/lon coordinates
      - optimization weights
      - language preference
    """

    def __init__(self, window_size: int = 5):
        self._window_size   = window_size
        self._turns: Deque[ConversationTurn] = deque(maxlen=window_size)
        self._turn_counter  = 0
        self._lock          = threading.Lock()

        #  Persistent text context 
        self._last_origin:       Optional[str]             = None
        self._last_destination:  Optional[str]             = None
        self._last_optimization: Optional[OptimizationGoal] = None
        self._last_weights:      Optional[WeightVector]    = None
        self._last_language:     Language                  = Language.ARABIC

        #  Persistent coordinates (lat/lon) 
        # Stored after geo resolution so followup can reuse without geo call
        self._last_origin_lat:       Optional[float] = None
        self._last_origin_lon:       Optional[float] = None
        self._last_destination_lat:  Optional[float] = None
        self._last_destination_lon:  Optional[float] = None

        #  Display cursor for pagination 
        # Tracks how many ranked journeys have been shown so far
        # After initial display of N: cursor = N
        # After show_more:            cursor = N + N
        self._display_cursor: int = 0

        #  Cached journey lists (survive window slides) 
        # When deque slides oldest turn off, these keep journey data available
        self._cached_all_journeys:    List[Journey] = []
        self._cached_ranked_journeys: List[Journey] = []

    
    # Write
    

    def save_turn(
        self,
        user_input:         str,
        intent:             Intent,
        all_journeys:       list,
        ranked_journeys:    list,
        displayed_journeys: list,
        response_text:      str  = "",
        was_followup:       bool = False,
        was_clarification:  bool = False,
        #coordinates from geo resolution  
        origin_coord:       Optional[Coordinate] = None,
        dest_coord:         Optional[Coordinate] = None,
    ) -> int:
        """
        Save a conversation turn.

        Args:
            origin_coord: Resolved origin Coordinate — stored for followup reuse
            dest_coord:   Resolved destination Coordinate — stored for followup reuse

        Returns:
            turn_id integer
        """
        with self._lock:
            self._turn_counter += 1
            turn = ConversationTurn(
                turn_id=self._turn_counter,
                user_input=user_input,
                intent=intent,
                all_journeys=list(all_journeys),
                ranked_journeys=list(ranked_journeys),
                displayed_journeys=list(displayed_journeys),
                response_text=response_text,
                timestamp=datetime.now(),
                was_followup=was_followup,
                was_clarification=was_clarification,
            )
            self._turns.append(turn)

            # Update persistent context (only for relevant turn types)
            self._update_persistent_context(intent)

            # Store coordinates if provided (journey + followup turns)
            if origin_coord is not None:
                self._last_origin_lat = origin_coord.lat
                self._last_origin_lon = origin_coord.lon
            if dest_coord is not None:
                self._last_destination_lat = dest_coord.lat
                self._last_destination_lon = dest_coord.lon

            # Cache journey lists so they survive window sliding
            if all_journeys:
                self._cached_all_journeys    = list(all_journeys)
                self._cached_ranked_journeys = list(ranked_journeys)

            # Advance cursor after journey display turns
            # so show_more correctly reads ranked[cursor:cursor+N]
            is_display_turn = (
                len(displayed_journeys) > 0
                and not was_clarification
            )
            if is_display_turn and not was_followup:
                # New search: cursor = number shown
                self._display_cursor = len(displayed_journeys)
            elif is_display_turn and was_followup:
                # Followup re-rank: reset cursor to number shown
                self._display_cursor = len(displayed_journeys)

            logger.debug(
                "turn_saved",
                turn_id=self._turn_counter,
                query_type=intent.query_type,
                journeys_count=len(all_journeys),
                cursor=self._display_cursor,
            )
            return self._turn_counter

    def _update_persistent_context(self, intent: Intent) -> None:
        """
        Update persistent fields from the latest intent.

        Only updates origin/destination for JOURNEY_REQUEST turns —
        avoids info/clarify turns accidentally overwriting real locations.
        """
        #  Language always updates 
        self._last_language = intent.language

        #  Origin/destination: only for journey-type intents 
        is_journey_type = intent.query_type in (
            QueryType.JOURNEY_REQUEST,
            QueryType.FOLLOWUP,
        )
        if is_journey_type:
            if intent.origin:
                self._last_origin      = intent.origin
            if intent.destination:
                self._last_destination = intent.destination

        #  Optimization weights 
        if (
            intent.optimization
            and intent.optimization != OptimizationGoal.SAME_AS_BEFORE
        ):
            self._last_optimization = intent.optimization
            self._last_weights      = intent.weights

    def advance_cursor(self, step: int = 3) -> None:
        """
        Move display cursor forward for show_more pagination.
        Called by agent._handle_show_more() after displaying a batch.
        """
        with self._lock:
            self._display_cursor += step

    def reset_cursor(self) -> None:
        """
        Reset pagination cursor.
        Called by agent on new journey search BEFORE saving turn
        (save_turn will then set cursor = len(displayed)).
        """
        with self._lock:
            self._display_cursor = 0

    
    # Read
    

    def get_context(self) -> MemoryContext:
        """
        Build MemoryContext snapshot for the controller.
        Thread-safe read.

        Journey lists come from cached versions (survive window sliding).
        Only displayed_journeys comes from last_turn (most recent display).
        """
        with self._lock:
            last_turn = self._turns[-1] if self._turns else None

            # Use cached journey lists — survive window sliding
            # Use last_turn's displayed_journeys — most recent display window
            all_journeys       = self._cached_all_journeys
            ranked_journeys    = self._cached_ranked_journeys
            displayed_journeys = last_turn.displayed_journeys if last_turn else []

            return MemoryContext(
                has_active_journeys=(len(all_journeys) > 0),
                all_journeys=all_journeys,
                ranked_journeys=ranked_journeys,
                displayed_journeys=displayed_journeys,
                display_cursor=self._display_cursor,

                last_origin=self._last_origin,
                last_destination=self._last_destination,

                #  Coordinates (lat/lon) — for followup routing 
                last_origin_lat=self._last_origin_lat,
                last_origin_lon=self._last_origin_lon,
                last_destination_lat=self._last_destination_lat,
                last_destination_lon=self._last_destination_lon,

                last_optimization=self._last_optimization,
                last_weights=self._last_weights,
                turn_count=self._turn_counter,
                last_intent=last_turn.intent if last_turn else None,
            )

    def get_latest_turn(self) -> Optional[ConversationTurn]:
        """Return most recent ConversationTurn."""
        with self._lock:
            return self._turns[-1] if self._turns else None

    
    # Intent resolution

    def resolve_intent(self, intent: Intent) -> Intent:
        """
        Fill missing fields from memory context.

        Returns a COPY of intent with filled fields —
        never mutates the passed object (defensive, thread-safe).

        Fields resolved:
          - origin      → from _last_origin if None
          - destination → from _last_destination if None
          - weights     → from _last_weights if SAME_AS_BEFORE
        """
        with self._lock:
            #  Copy intent to avoid mutating shared object 
            # Pydantic model_copy() creates a shallow copy
            resolved = intent.model_copy()

            #  Fill origin 
            if resolved.origin is None and self._last_origin:
                resolved.origin = self._last_origin
                logger.debug(
                    "intent_origin_resolved_from_memory",
                    origin=self._last_origin,
                )

            #  Fill destination 
            if resolved.destination is None and self._last_destination:
                resolved.destination = self._last_destination
                logger.debug(
                    "intent_destination_resolved_from_memory",
                    destination=self._last_destination,
                )

            #  Fill weights for SAME_AS_BEFORE 
            if (
                resolved.optimization == OptimizationGoal.SAME_AS_BEFORE
                and self._last_weights is not None
            ):
                resolved.optimization = (
                    self._last_optimization or OptimizationGoal.BALANCED
                )
                resolved.weights = self._last_weights
                logger.debug(
                    "intent_weights_resolved_from_memory",
                    optimization=resolved.optimization,
                )

            return resolved

    def detect_topic_shift(self, intent: Intent) -> bool:
        """
        Returns True if origin OR destination meaningfully changed.
        Uses normalized text comparison to avoid false positives
        from Arabic spelling variants (ال prefix, tashkeel etc.)

        Examples:
          "العصافرة" vs "عصافرة"  -> NOT a shift (normalized same)
          "العصافرة" vs "سيدي بشر" -> IS a shift
        """
        with self._lock:
            if not self._last_origin and not self._last_destination:
                return False   # no previous context

            def _normalized(text: Optional[str]) -> str:
                if not text:
                    return ""
                return TextNormalizer.normalize(text)
            
            origin_shifted = (
                intent.origin is not None
                and self._last_origin is not None
                and _normalized(intent.origin) != _normalized(self._last_origin)
            )
            dest_shifted = (
                intent.destination is not None
                and self._last_destination is not None
                and _normalized(intent.destination) != _normalized(self._last_destination)
            )

            shifted = origin_shifted or dest_shifted

            if shifted:
                logger.info(
                    "topic_shift_detected",
                    old_origin=self._last_origin,
                    new_origin=intent.origin,
                    old_dest=self._last_destination,
                    new_dest=intent.destination,
                )
            return shifted

    def clear(self) -> None:
        """Full reset — called on session end or explicit clear command."""
        with self._lock:
            self._turns.clear()
            self._turn_counter          = 0
            self._last_origin           = None
            self._last_destination      = None
            self._last_optimization     = None
            self._last_weights          = None
            self._last_language         = Language.ARABIC  # default 
            self._last_origin_lat       = None
            self._last_origin_lon       = None
            self._last_destination_lat  = None
            self._last_destination_lon  = None
            self._display_cursor        = 0
            self._cached_all_journeys   = []
            self._cached_ranked_journeys = []
            logger.info("memory_cleared")



# Session store — maps session_id -> ConversationMemory



class SessionStore:
    """
    In-memory store of all active sessions.
    Each session_id gets its own ConversationMemory.

    Thread-safe. TTL-based eviction + LRU overflow eviction.
    """

    def __init__(
        self,
        window_size:         int = 5, 
        max_sessions:        int = 1000, 
        session_ttl_minutes: int = 30, 
    ):
        self._sessions:     Dict[str, ConversationMemory] = {}
        self._last_access:  Dict[str, datetime]           = {}
        self._window_size           = window_size
        self._max_sessions          = max_sessions
        self._session_ttl_minutes   = session_ttl_minutes
        self._lock                  = threading.Lock()

    def get(self, session_id: str) -> ConversationMemory:
        """
        Get or create memory for a session.
        Auto-creates if not found. Auto-evicts stale sessions.
        """
        with self._lock:
            self._evict_stale_sessions()

            if session_id not in self._sessions:
                if len(self._sessions) >= self._max_sessions:
                    self._evict_oldest_session()
                self._sessions[session_id] = ConversationMemory(
                    window_size=self._window_size
                )
                logger.info("session_created", session_id=session_id)

            self._last_access[session_id] = datetime.now()
            return self._sessions[session_id]

    def delete(self, session_id: str) -> None:
        """Explicitly delete a session."""
        with self._lock:
            self._sessions.pop(session_id, None)
            self._last_access.pop(session_id, None)
            logger.info("session_deleted", session_id=session_id)

    def _evict_stale_sessions(self) -> None:
        """Remove sessions inactive longer than TTL."""
        now   = datetime.now()
        stale = [
            sid
            for sid, last in self._last_access.items()
            if (now - last).total_seconds() > self._session_ttl_minutes * 60
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
            self._last_access.pop(sid, None)
            logger.info("session_evicted_ttl", session_id=sid)

    def _evict_oldest_session(self) -> None:
        """Remove least-recently-used session when at capacity."""
        if not self._last_access:
            return
        oldest = min(self._last_access, key=self._last_access.get)
        self._sessions.pop(oldest, None)
        self._last_access.pop(oldest, None)
        logger.info("session_evicted_lru", session_id=oldest)

    @property
    def active_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)


#  Singleton session store 

_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Singleton session store factory."""
    global _session_store
    if _session_store is None:
        from config import settings
        _session_store = SessionStore(
            window_size=settings.memory_window_size,
        )
    return _session_store