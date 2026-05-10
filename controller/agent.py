"""
agent.py
Main orchestrator — the central brain of the system.

Full request lifecycle:
  1. Parse intent (Qwen2.5 model -> Intent JSON) how? ans : get_intent_parser() returns IntentParser instance with parse() method that calls Qwen API and converts to Intent object.
  2. Get memory context (per session) How ? ans : ConversationMemory class with get_context() method that returns current context based on past turns.
  3. Resolve missing fields from memory how? ans : ConversationMemory class with resolve_intent() method that fills in missing origin/destination from last known values in context.
  4. Detect topic shift how? ans : ConversationMemory class with detect topic_shift() method that compares new intent's origin/destination with last known ones to see if user switched to a new journey.
  5. Route to correct handler (router.py) how? ans : ScenarioRouter class with route() method that takes intent + context and returns handler name based on rules.
  6. Execute handler (geo -> routing → ranking → db) how? ans : Each handler method (e.g. _handle_journey) implements the full pipeline for that scenario, calling geo_tool, routing_tool, ranking_layer, db_tool as needed.
  7. Build response (response_builder.py) how? ans : ResponseBuilder class with methods like build_journey_response() that take journeys + intent and return user-facing text.
  8. Save turn to memory how? ans : ConversationMemory class with save_turn() method that stores user_input, intent, journeys, response_text, and other metadata for the current turn.
  9. Return AgentResponse how? ans : AgentResponse dataclass that includes text, language, journeys, intent, and other fields to be returned to the user.

Handler map:
  handle_journey        -> geo + routing + ranking → new results
  handle_followup       -> re-rank OR new routing (if restricted_modes changed)
  handle_info           -> db_tool -> fare/schedule/line info
  handle_show_more      -> paginate ranked_journeys
  handle_show_detail    -> detail view of one journey
  handle_missing_fields -> ask user for origin/destination
  handle_no_context     -> user did follow-up with no active journeys
  handle_no_more        -> user asked show_more but cursor at end
  handle_clarify        -> unknown intent, ask to rephrase
"""

from __future__ import annotations 

from pathlib import Path
from typing import List, Optional, Set

import sys
sys.path.append(str(Path(__file__).parent.parent)) 

from config import settings
from model.intent.schema import (
    AgentResponse,
    Coordinate,
    Intent,
    Journey,
    Language,
    MemoryContext,
    QueryType,
    StopRecord,
    TransportMode,
    WeightVector,
)
from model.intent.inference import get_intent_parser
from model.memory.conversation import ConversationMemory, get_session_store
from model.ranking import RankingLayer
from controller.router import ScenarioRouter
from controller.tools.geo_tool import GeoTool
from controller.tools.routing_tool import RoutingTool
from controller.tools.db_tool import DBTool
from view.response_builder import ResponseBuilder
import structlog 

logger = structlog.get_logger(__name__) 


class TransportAgent:
    """
    Main agent orchestrator.

    One instance per application — shared across all sessions.
    Session state is isolated in ConversationMemory per session_id. what is the benefit of this approach?
    Benefits of using ConversationMemory per session_id:
    1. Isolation: Each user's conversation state is kept separate, preventing data leakage between sessions and ensuring privacy.
    2. Scalability: The agent can handle multiple concurrent users without interference, as each session has its own memory instance.
    3. Simplicity: The agent logic can focus on processing one session at a time, while ConversationMemory manages the complexity of storing and retrieving past interactions.
    4. Flexibility: ConversationMemory can implement features like TTL-based eviction, LRU cleanup, and context resolution without affecting the core agent logic.

    Thread-safe: all tools are stateless.
    Session state lives in _session_store (dict per session_id).
    """

    def __init__(self, adapter_path: Optional[str] = None):
        # Core components (shared, stateless)  
        self._intent_parser = get_intent_parser(adapter_path)
        self._ranking_layer = RankingLayer(auto_load_ltr=True)
        self._router        = ScenarioRouter()
        self._geo_tool      = GeoTool()
        self._routing_tool  = RoutingTool()
        self._db_tool       = DBTool()
        self._view          = ResponseBuilder()

        # Session store (per-session state)  
        self._session_store = get_session_store() 

        logger.info(
            "transport_agent_initialized",
            adapter_path=adapter_path or "default",
            model=settings.model.name,
        )


    # Public API 

    def handle(
        self,
        user_input: str,
        session_id: str,
    ) -> AgentResponse: 
        """
        Main entry point. Never raises — always returns AgentResponse.

        Args:
            user_input: Raw user message (Arabic or English)
            session_id: Unique session identifier

        Returns:
            AgentResponse with text + journeys + metadata
        """
        try:
            return self._handle_safe(user_input, session_id) 
        except Exception as e:
            logger.error(
                "agent_unhandled_error",
                error=str(e),
                error_type=type(e).__name__,
                session_id=session_id,
                user_input=user_input[:100],
            )
            return AgentResponse(
                text=self._view.api_error(),
                language=Language.ARABIC,
                error=str(e),
            )
 
    # Internal pipeline 

    def _handle_safe(
        self,
        user_input: str,
        session_id: str,
    ) -> AgentResponse:
        """Full pipeline — called inside try/except in handle()."""

        # 1. Get session memory
        memory = self._session_store.get(session_id) 

        # 2. Parse intent 
        intent = self._intent_parser.parse(user_input)
        logger.info(
            "intent_parsed",
            session_id=session_id,
            query_type=intent.query_type,
            origin=intent.origin,
            destination=intent.destination,
            optimization=intent.optimization,
            language=intent.language,
        )

        # 3. Get current memory context  
        context = memory.get_context()

        # 4. Resolve missing fields from memory  
        # MUST happen before router.route() — router checks intent.missing_fields
        intent = memory.resolve_intent(intent)

        # 5. Detect topic shift  
        # If user provides new origin/destination → treat as fresh journey
        topic_shifted = memory.detect_topic_shift(intent)
        if topic_shifted and intent.query_type == QueryType.FOLLOWUP: 
            intent.query_type = QueryType.JOURNEY_REQUEST
            logger.info(
                "followup_reclassified_as_journey",
                session_id=session_id,
                new_origin=intent.origin,
                new_destination=intent.destination,
            )

        # 6. Route to handler 
        handler_name = self._router.route(intent, context)  
        logger.info(
            "routing_decision",
            session_id=session_id,
            handler=handler_name,
            query_type=intent.query_type,
        )

        # 7. Dispatch 
        handler_map = {
            "handle_journey":        self._handle_journey,
            "handle_followup":       self._handle_followup,
            "handle_info":           self._handle_info,
            "handle_show_more":      self._handle_show_more,
            "handle_show_detail":    self._handle_show_detail,
            "handle_missing_fields": self._handle_missing_fields,
            "handle_no_context":     self._handle_no_context,
            "handle_no_more":        self._handle_no_more,    
            "handle_clarify":        self._handle_clarify,
        }

        handler = handler_map.get(handler_name, self._handle_clarify)
        return handler(
            user_input=user_input,
            intent=intent,
            context=context,
            memory=memory,
        )

    
   
    # Geo resolution helper
   
    def _resolve_coordinates(
        self,
        intent:  Intent,
        context: MemoryContext,
        lang:    Language,
    ) -> tuple[Optional[Coordinate], Optional[Coordinate], Optional[AgentResponse]]:
        """
        Resolve origin + destination → Coordinate objects.

        Tries:
          1. Fresh geo resolution via geo_tool (pg_trgm + Nominatim)
          2. Falls back to cached coordinates in memory context

        Returns:
            (origin_coord, dest_coord, error_response)
            error_response is set if resolution fails — caller should return it.
        """
        # Origin 
        origin_record = self._geo_tool.resolve(intent.origin)

        if origin_record is None or not origin_record.has_coordinates:
            # Try memory fallback
            if context.last_origin_lat and context.last_origin_lon:
                origin_coord = Coordinate(
                    lat=context.last_origin_lat,
                    lon=context.last_origin_lon,
                )
                logger.info(
                    "geo_origin_fallback_to_memory",
                    origin=intent.origin,
                )
            else:
                error = AgentResponse(
                    text=self._view.stop_not_found(intent.origin, lang),
                    language=lang,
                )
                return None, None, error
        else:
            origin_coord = origin_record.coordinate

        # Destination  
        dest_record = self._geo_tool.resolve(intent.destination)

        if dest_record is None or not dest_record.has_coordinates:
            # Try memory fallback
            if context.last_destination_lat and context.last_destination_lon:
                dest_coord = Coordinate(
                    lat=context.last_destination_lat,
                    lon=context.last_destination_lon,
                )
                logger.info(
                    "geo_destination_fallback_to_memory",
                    destination=intent.destination,
                )
            else:
                error = AgentResponse(
                    text=self._view.stop_not_found(intent.destination, lang),
                    language=lang,
                )
                return None, None, error
        else:
            dest_coord = dest_record.coordinate

        return origin_coord, dest_coord, None
 

    # Handlers 

    def _handle_journey(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        Scenario: Full journey search.

        Pipeline:
          geo_tool → Coordinate objects
          routing_tool.get_journeys(origin, dest, weights)
          ranking_layer.rank(journeys, weights, constraints)
          response_builder → text
          memory.save_turn()
        """
        lang = intent.language

        # Geo resolution -> Coordinates  
        origin_coord, dest_coord, error = self._resolve_coordinates(
            intent, context, lang
        )
        if error:
            return error

        # Routing engine -> raw journeys  
        # Pass weights so engine does initial scoring aligned with user intent
        all_journeys = self._routing_tool.get_journeys(
            origin=origin_coord,           #  Coordinate object
            destination=dest_coord,        #  Coordinate object
            weights=intent.weights,        #  WeightVector -> RoutingWeights inside tool
            top_k=settings.routing.top_k,
        )

        if not all_journeys:
            text = self._view.no_route_found(
                intent.origin, intent.destination, lang
            )
            memory.save_turn(
                user_input=user_input,
                intent=intent,
                all_journeys=[],
                ranked_journeys=[],
                displayed_journeys=[],
                response_text=text,
            )
            return AgentResponse(text=text, language=lang)

        # Ranking -> sorted + filtered journeys 
        ranked_journeys = self._ranking_layer.rank(
            journeys=all_journeys,
            weights=intent.weights,
            constraints=intent.constraints,
            language=lang.value,
        )

        # Check if constraints filtered everything  
        # ranked_journeys empty AND we had constraints -> all filtered out
        all_filtered = (
            len(intent.constraints) > 0
            and len(ranked_journeys) == 0   #  was wrong condition
        )
        if all_filtered:
            # Fallback: show unconstrained results with warning
            ranked_journeys = self._ranking_layer.rank(
                journeys=all_journeys,
                weights=intent.weights,
                constraints=[],            # ← no constraints
                language=lang.value,
            )

        # Pagination window 
        max_display = settings.max_displayed_journeys
        displayed   = ranked_journeys[:max_display]
        has_more    = len(ranked_journeys) > max_display

        memory.reset_cursor()

        # Build response 
        prefix = self._view.all_filtered(lang) + "\n\n" if all_filtered else ""
        text = prefix + self._view.build_journey_response(
            journeys=displayed,
            intent=intent,
            has_more=has_more,
            is_followup=False,
        )

        # Save to memory  
        # Stores coordinates so followup can reuse without geo call
        memory.save_turn(
            user_input=user_input,
            intent=intent,
            all_journeys=all_journeys,
            ranked_journeys=ranked_journeys,
            displayed_journeys=displayed,
            response_text=text,
            was_followup=False,
            origin_coord=origin_coord,     # store for followup reuse
            dest_coord=dest_coord,         # store for followup reuse
        )

        return AgentResponse(
            text=text,
            language=lang,
            journeys=displayed,
            intent=intent,
            has_more=has_more,
        )

    def _handle_followup(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        Scenario: Follow-up on existing results.

        Two sub-cases:
          A. Weight change only (e.g. "أرخص") → re-rank existing journeys
          B. Mode restriction added (e.g. "بدون ميكروباص") → new routing call

        Case B needs a new routing call because the routing engine
        must exclude the restricted mode from its graph traversal.
        """
        lang         = intent.language
        all_journeys = context.all_journeys

        # Detect if restricted_modes changed -> need new routing call
        needs_new_routing = (
            len(intent.info_params.get("restricted_modes", [])) > 0
            and context.last_origin_lat is not None
            and context.last_destination_lat is not None
        )

        if needs_new_routing:
            # Re-call routing engine with restricted modes
            origin_coord = Coordinate(
                lat=context.last_origin_lat,
                lon=context.last_origin_lon,
            )
            dest_coord = Coordinate(
                lat=context.last_destination_lat,
                lon=context.last_destination_lon,
            )
            all_journeys = self._routing_tool.get_journeys(
                origin=origin_coord,
                destination=dest_coord,
                weights=intent.weights,
                top_k=settings.routing.top_k,
            )
            logger.info(
                "followup_new_routing_call",
                restricted_modes=intent.info_params.get("restricted_modes"),
                journeys_returned=len(all_journeys),
            )

        # Re-rank with new weights 
        # Use intent weights; fall back to previous if intent is still balanced default
        weights = intent.weights
        is_default_weights = (
            abs(weights.cost - 0.25) < 0.01
            and abs(weights.time - 0.25) < 0.01
        )
        if is_default_weights and context.last_weights is not None:
            weights = context.last_weights

        ranked_journeys = self._ranking_layer.rank(
            journeys=all_journeys,
            weights=weights,
            constraints=intent.constraints or [],
            language=lang.value,
        )

        max_display = settings.max_displayed_journeys
        displayed   = ranked_journeys[:max_display]
        has_more    = len(ranked_journeys) > max_display

        memory.reset_cursor()

        text = self._view.build_followup_response(
            journeys=displayed,
            intent=intent,
            has_more=has_more,
        )

        memory.save_turn(
            user_input=user_input,
            intent=intent,
            all_journeys=all_journeys,
            ranked_journeys=ranked_journeys,
            displayed_journeys=displayed,
            response_text=text,
            was_followup=True,
        )

        return AgentResponse(
            text=text,
            language=lang,
            journeys=displayed,
            intent=intent,
            has_more=has_more,
        )

    def _handle_info(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        Scenario: Info request (fare / schedule / line_info).
        Queries db_tool directly — no routing engine.
        """
        lang = intent.language

        info_data = self._db_tool.query(
            info_target=intent.info_target or "fare",
            info_params=intent.info_params,
        )

        text = self._view.build_info_response(
            info_data=info_data,
            info_target=intent.info_target or "fare",
            info_params=intent.info_params,
            language=lang,
        )

        memory.save_turn(
            user_input=user_input,
            intent=intent,
            all_journeys=[],
            ranked_journeys=[],
            displayed_journeys=[],
            response_text=text,
        )

        return AgentResponse(
            text=text,
            language=lang,
            intent=intent,
        )

    def _handle_show_more(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        Pagination: show next batch of ranked journeys.

        cursor tracks how many have been shown so far.
        Initial display: ranked[0:max_display], cursor = max_display
        Show more:       ranked[cursor:cursor+max_display]
        """
        lang        = intent.language
        ranked      = context.ranked_journeys
        cursor      = context.display_cursor      # how many shown so far
        max_display = settings.max_displayed_journeys
        next_batch = ranked[cursor : cursor + max_display]

        if not next_batch:
            text = self._view.no_more_results(lang)
            return AgentResponse(text=text, language=lang)

        has_more = len(ranked) > cursor + max_display

        # Advance cursor by what we're about to show
        memory.advance_cursor(step=max_display)

        text = self._view.build_pagination_response(
            journeys=next_batch,
            intent=intent,
            has_more=has_more,
        )

        memory.save_turn(
            user_input=user_input,
            intent=intent,
            all_journeys=context.all_journeys,
            ranked_journeys=ranked,
            displayed_journeys=next_batch,
            response_text=text,
        )

        return AgentResponse(
            text=text,
            language=lang,
            journeys=next_batch,
            intent=intent,
            has_more=has_more,
        )

    def _handle_show_detail(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        Show detailed breakdown for a specific journey.

        result_index from intent is 1-based (user says "الثانية" → 2).
        Convert to 0-based for list access.
        """
        lang      = intent.language
        displayed = context.displayed_journeys

        if not displayed:
            return AgentResponse(
                text=self._view.no_context(lang),
                language=lang,
            )
 
        raw_idx  = intent.result_index if intent.result_index is not None else 1
        idx      = max(0, min(raw_idx - 1, len(displayed) - 1)) 

        journey  = displayed[idx]
        text     = self._view.build_detail_response(journey, intent)

        return AgentResponse(
            text=text,
            language=lang,
            journeys=[journey],
            intent=intent,
        )

    def _handle_missing_fields(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        Ask user for missing origin or destination.
        Saves turn so memory knows we're mid-journey-request.
        """
        lang = intent.language
        text = self._view.ask_missing(intent.missing_fields, lang)

        memory.save_turn(
            user_input=user_input,
            intent=intent,
            all_journeys=[],
            ranked_journeys=[],
            displayed_journeys=[],
            response_text=text,
            was_clarification=True,
        )

        return AgentResponse(text=text, language=lang, intent=intent)

    def _handle_no_context(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        User tried follow-up / show_more but no active journeys in memory.
        Prompt them to start a new search.
        """
        lang = intent.language
        text = self._view.no_context(lang)
        return AgentResponse(text=text, language=lang)

    def _handle_no_more(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        User asked 'show more' but cursor is at end of ranked_journeys.
        Tell them there are no more results.
        """
        lang = intent.language
        text = self._view.no_more_results(lang)
        return AgentResponse(text=text, language=lang)

    def _handle_clarify(
        self,
        user_input: str,
        intent:     Intent,
        context:    MemoryContext,
        memory:     ConversationMemory,
    ) -> AgentResponse:
        """
        Unrecognized query — ask user to rephrase.
        """
        lang = intent.language    # always set — Intent has default Language.ARABIC
        text = self._view.clarify(lang)
        return AgentResponse(text=text, language=lang)