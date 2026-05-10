"""Unit tests for conversation memory."""
import pytest
from model.memory.conversation import ConversationMemory
from model.intent.schema import Intent, QueryType, Language, OptimizationGoal


def make_intent(**kwargs) -> Intent:
    defaults = dict(
        query_type=QueryType.JOURNEY_REQUEST,
        origin="سموحة",
        destination="العصافرة",
        language=Language.ARABIC,
    )
    defaults.update(kwargs)
    return Intent(**defaults)


class TestConversationMemory:

    def setup_method(self):
        self.memory = ConversationMemory(window_size=5)

    def test_save_and_retrieve(self):
        intent = make_intent()
        self.memory.save_turn(
            user_input="test",
            intent=intent,
            all_journeys=[],
            ranked_journeys=[],
            displayed_journeys=[],
        )
        ctx = self.memory.get_context()
        assert ctx.last_origin == "سموحة"
        assert ctx.last_destination == "العصافرة"

    def test_resolve_missing_origin(self):
        # First turn sets origin
        self.memory.save_turn(
            user_input="t1",
            intent=make_intent(origin="سموحة", destination="العصافرة"),
            all_journeys=[],
            ranked_journeys=[],
            displayed_journeys=[],
        )
        # Second turn has no origin
        follow_intent = make_intent(
            query_type=QueryType.FOLLOWUP,
            origin=None,
            destination=None,
        )
        resolved = self.memory.resolve_intent(follow_intent)
        assert resolved.origin == "سموحة"
        assert resolved.destination == "العصافرة"

    def test_topic_shift_detected(self):
        self.memory.save_turn(
            user_input="t1",
            intent=make_intent(origin="سموحة", destination="العصافرة"),
            all_journeys=[],
            ranked_journeys=[],
            displayed_journeys=[],
        )
        new_intent = make_intent(origin="العوايد", destination="سيدي بشر")
        assert self.memory.detect_topic_shift(new_intent) is True

    def test_no_topic_shift_same_location(self):
        self.memory.save_turn(
            user_input="t1",
            intent=make_intent(origin="سموحة", destination="العصافرة"),
            all_journeys=[],
            ranked_journeys=[],
            displayed_journeys=[],
        )
        follow = make_intent(
            query_type=QueryType.FOLLOWUP,
            origin=None,
            destination=None,
        )
        assert self.memory.detect_topic_shift(follow) is False

    def test_window_size_respected(self):
        for i in range(7):
            self.memory.save_turn(
                user_input=f"turn {i}",
                intent=make_intent(),
                all_journeys=[],
                ranked_journeys=[],
                displayed_journeys=[],
            )
        assert self.memory._turn_counter == 7
        assert len(self.memory._turns) == 5  # window=5

    def test_clear_resets_all(self):
        self.memory.save_turn(
            user_input="t",
            intent=make_intent(),
            all_journeys=[],
            ranked_journeys=[],
            displayed_journeys=[],
        )
        self.memory.clear()
        ctx = self.memory.get_context()
        assert ctx.last_origin is None
        assert ctx.has_active_journeys is False