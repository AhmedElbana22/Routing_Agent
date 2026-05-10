"""Unit tests for rule-based parser (no model needed)."""
import pytest
from model.intent.inference import RuleBasedParser, LanguageDetector
from model.intent.schema import Language, QueryType, OptimizationGoal


class TestLanguageDetector:

    def test_arabic(self):
        assert LanguageDetector.detect("عايز أروح من رمسيس") == Language.ARABIC

    def test_english(self):
        assert LanguageDetector.detect("I want to go from Ramsis") == Language.ENGLISH

    def test_mixed(self):
        assert LanguageDetector.detect("عايز أروح from Ramsis") == Language.MIXED


class TestRuleBasedParser:

    def setup_method(self):
        self.parser = RuleBasedParser()

    def test_arabic_journey(self):
        intent = self.parser.parse("عايز أروح من رمسيس لـالمطار")
        assert intent.query_type == QueryType.JOURNEY_REQUEST
        assert intent.origin == "رمسيس"
        assert intent.destination == "المطار"

    def test_english_journey(self):
        intent = self.parser.parse("I want to go from Ramsis to the Airport")
        assert intent.query_type == QueryType.JOURNEY_REQUEST
        assert intent.origin is not None
        assert intent.destination is not None

    def test_min_time_optimization(self):
        intent = self.parser.parse("أسرع طريقة من رمسيس للمطار")
        assert intent.optimization == OptimizationGoal.MIN_TIME

    def test_min_cost_optimization(self):
        intent = self.parser.parse("أرخص طريقة من رمسيس للمطار")
        assert intent.optimization == OptimizationGoal.MIN_COST

    def test_fare_constraint(self):
        intent = self.parser.parse("من رمسيس للمطار مش أكتر من 20 جنيه")
        assert len(intent.constraints) > 0
        assert intent.constraints[0].field == "fare"
        assert intent.constraints[0].value == 20.0

    def test_followup_detection(self):
        intent = self.parser.parse("طب وإيه لو أسرع؟")
        assert intent.query_type == QueryType.FOLLOWUP

    def test_show_more(self):
        intent = self.parser.parse("وريني أكتر")
        assert intent.query_type == QueryType.SHOW_MORE

    def test_empty_input(self):
        intent = self.parser.parse("")
        assert intent.query_type == QueryType.UNKNOWN

    def test_never_raises(self):
        """Parser should never raise even on garbage input."""
        for bad_input in ["!!!", "   ", "123456", "اااا", "????"]:
            intent = self.parser.parse(bad_input)
            assert intent is not None