"""
router.py
Scenario router — decides which handler to call
based on query_type and memory context.

Pure routing logic only — no business logic here.

Handler names returned:
  "handle_journey"        -> new journey request (origin + destination resolved)
  "handle_followup"       -> follow-up on existing results (optimization change)
  "handle_show_more"      -> paginate to next batch of results
  "handle_show_detail"    -> show detail of specific result by index
  "handle_info"           -> info request (fare/schedule/line_info)
  "handle_missing_fields" -> journey request but origin/destination still missing
  "handle_no_context"     -> follow-up/show_more but no active journeys in memory
  "handle_no_more"        -> show_more requested but cursor is at end of results
  "handle_clarify"        -> unknown intent or clarification needed

Important ordering note:
  agent.py MUST call conversation.resolve_missing_fields(intent, context)
  BEFORE calling router.route() — otherwise missing_fields check is premature.
"""

from __future__ import annotations

from pathlib import Path

import sys
sys.path.append(str(Path(__file__).parent.parent))

from model.intent.schema import Intent, MemoryContext, QueryType
import structlog

logger = structlog.get_logger(__name__)


class ScenarioRouter:
    """
    Maps (query_type, context_state) → handler name string.

    Returns a string handler name, not a callable —
    keeps routing logic pure and independently testable.

    agent.py maps handler names → actual methods:
      _handlers = {
          "handle_journey":        self._handle_journey,
          "handle_followup":       self._handle_followup,
          ...
      }
    """
    
    def route(
        self,
        intent:  Intent,
        context: MemoryContext,
    ) -> str:
        """
        Determine which handler to invoke.

        Args:
            intent:  Parsed + memory-resolved Intent
                     (agent.py resolves missing fields BEFORE calling this)
            context: Current MemoryContext from conversation.py

        Returns:
            Handler name string (see module docstring for full list)
        """
        qt = intent.query_type

        # 1. Unknown query type 
        if qt == QueryType.UNKNOWN:
            logger.info("routing_to_clarify", reason="unknown_query_type")
            return "handle_clarify"

        # 2. Clarification explicitly needed  
        # Placed before journey check — model flagged this as ambiguous
        if qt == QueryType.CLARIFICATION_NEEDED:
            logger.info("routing_to_clarify", reason="model_flagged_clarification")
            return "handle_clarify"

        # 3. Journey request 
        # Note: agent.py must resolve missing fields from memory BEFORE here.
        # If fields are still missing after memory resolution → ask user.
        if qt == QueryType.JOURNEY_REQUEST:
            if intent.missing_fields:
                logger.info(
                    "routing_to_missing_fields",
                    missing=intent.missing_fields,
                    origin=intent.origin,
                    destination=intent.destination,
                )
                return "handle_missing_fields"

            logger.info(
                "routing_to_journey",
                origin=intent.origin,
                destination=intent.destination,
                optimization=intent.optimization,
            )
            return "handle_journey"

        # 4. Follow-up 
        # User is refining/asking about previous results.
        # Requires active journeys in memory.
        #
        # Sub-types handled inside handle_followup in agent.py:
        #   - optimization change -> re-rank existing or fetch new
        #   - "أرخص" / "أسرع" etc.
        if qt == QueryType.FOLLOWUP:
            if not context.has_active_journeys:
                logger.info(
                    "routing_to_no_context",
                    reason="followup_without_active_journeys",
                )
                return "handle_no_context"

            logger.info(
                "routing_to_followup",
                last_origin=context.last_origin,
                last_destination=context.last_destination,
                optimization=intent.optimization,
            )
            return "handle_followup"

        # 5. Show more (pagination)  
        # User wants next batch beyond the displayed_journeys.
        # Checks both: has results AND cursor not at end.
        if qt == QueryType.SHOW_MORE:
            if not context.has_active_journeys:
                logger.info(
                    "routing_to_no_context",
                    reason="show_more_without_active_journeys",
                )
                return "handle_no_context"

            # Check if there are actually more journeys beyond cursor
            total_ranked  = len(context.ranked_journeys)
            cursor        = context.display_cursor

            if cursor >= total_ranked:
                logger.info(
                    "routing_to_no_more",
                    cursor=cursor,
                    total=total_ranked,
                )
                return "handle_no_more"           

            logger.info(
                "routing_to_show_more",
                cursor=cursor,
                total=total_ranked,
                remaining=total_ranked - cursor,
            )
            return "handle_show_more"

        # 6. Show detail  
        # User wants detail on a specific result (e.g. "وضح التانية").
        # result_index comes from intent (model extracts "التانية" → 2)
        if qt == QueryType.SHOW_DETAIL:
            if not context.has_active_journeys:
                logger.info(
                    "routing_to_no_context",
                    reason="show_detail_without_active_journeys",
                )
                return "handle_no_context"

            logger.info(
                "routing_to_show_detail",
                result_index=intent.result_index,
            )
            return "handle_show_detail"

        # 7. Info request  
        # User asking about fare/schedule/line info.
        # Validate info_target is set — otherwise db_tool.query() wastes a call.
        if qt == QueryType.INFO_REQUEST:
            if not intent.info_target:
                logger.info(
                    "routing_to_clarify",
                    reason="info_request_missing_info_target",
                    raw_text=intent.raw_text,
                )
                return "handle_clarify"

            logger.info(
                "routing_to_info",
                target=intent.info_target,
                params=intent.info_params,
            )
            return "handle_info"

        # 8. Fallback  
        logger.warning(
            "routing_fallback_unhandled_query_type",
            query_type=qt,
            raw_text=intent.raw_text,
        )
        return "handle_clarify"