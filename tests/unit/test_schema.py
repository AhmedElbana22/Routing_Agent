"""
test_schema.py
Verifies all schema models validate correctly.
Run: pytest tests/unit/test_schema.py -v
"""
import pytest
from model.intent.schema import (
    WeightVector, Constraint, Intent, Journey, Step,
    QueryType, OptimizationGoal, Language, TransportMode,
    RouteRequest, Coordinate, ChatRequest, AgentResponse,
)


class TestCoordinate:

    def test_valid(self):
        c = Coordinate(lat=30.0626, lng=31.2497)
        assert c.lat == 30.0626
        assert c.lng == 31.2497

    def test_as_tuple(self):
        c = Coordinate(lat=30.0, lng=31.0)
        assert c.as_tuple == (30.0, 31.0)

    def test_invalid_lat(self):
        with pytest.raises(Exception):
            Coordinate(lat=100.0, lng=31.0)  # lat > 90


class TestRouteRequest:

    def test_valid_request(self):
        r = RouteRequest(
            start_lat=31.2001, start_lon=29.9187,
            end_lat=31.2156,   end_lon=29.9553,
        )
        assert r.start_lat == 31.2001
        assert r.max_transfers == 3    # default
        assert r.walking_cutoff == 1500  # default
        assert r.top_k == 10           # default

    def test_field_names_are_lon_not_lng(self):
        """API uses 'lon' not 'lng' — must match exactly."""
        r = RouteRequest(
            start_lat=31.0, start_lon=29.0,
            end_lat=31.1,   end_lon=29.1,
        )
        d = r.to_api_dict()
        assert "start_lon" in d   # NOT start_lng
        assert "end_lon"   in d   # NOT end_lng
        assert "start_lng" not in d
        assert "end_lng"   not in d

    # API bounds enforcement 

    def test_max_transfers_max_5(self):
        with pytest.raises(Exception):
            RouteRequest(
                start_lat=31.0, start_lon=29.0,
                end_lat=31.1,   end_lon=29.1,
                max_transfers=6,  # over API max
            )

    def test_walking_cutoff_min_100(self):
        with pytest.raises(Exception):
            RouteRequest(
                start_lat=31.0, start_lon=29.0,
                end_lat=31.1,   end_lon=29.1,
                walking_cutoff=50,  # under API min
            )

    def test_walking_cutoff_max_5000(self):
        with pytest.raises(Exception):
            RouteRequest(
                start_lat=31.0, start_lon=29.0,
                end_lat=31.1,   end_lon=29.1,
                walking_cutoff=6000,  # over API max
            )

    def test_top_k_max_20(self):
        with pytest.raises(Exception):
            RouteRequest(
                start_lat=31.0, start_lon=29.0,
                end_lat=31.1,   end_lon=29.1,
                top_k=21,  # over API max
            )

    def test_from_coordinates_clamps_values(self):
        """from_coordinates() auto-clamps to valid ranges."""
        origin = Coordinate(lat=31.0, lng=29.0)
        dest   = Coordinate(lat=31.1, lng=29.1)
        r = RouteRequest.from_coordinates(
            origin=origin,
            destination=dest,
            max_transfers=99,    # will be clamped to 5
            walking_cutoff=9999, # will be clamped to 5000
            top_k=100,           # will be clamped to 20
        )
        assert r.max_transfers  == 5
        assert r.walking_cutoff == 5000
        assert r.top_k          == 20

    def test_to_api_dict_has_all_required_fields(self):
        origin = Coordinate(lat=31.2001, lng=29.9187)
        dest   = Coordinate(lat=31.2156, lng=29.9553)
        r = RouteRequest.from_coordinates(origin=origin, destination=dest)
        d = r.to_api_dict()

        required_keys = {
            "start_lat", "start_lon", "end_lat", "end_lon",
            "max_transfers", "walking_cutoff", "top_k",
            "weight_time", "weight_cost", "weight_walk", "weight_transfer",
        }
        assert required_keys.issubset(d.keys())


class TestWeightVector:

    def test_auto_normalize(self):
        w = WeightVector(cost=2.0, time=2.0, transfers=2.0, walking=2.0)
        total = w.cost + w.time + w.transfers + w.walking
        assert abs(total - 1.0) < 0.001

    def test_all_zeros_fallback(self):
        w = WeightVector(cost=0.0, time=0.0, transfers=0.0, walking=0.0)
        assert w.cost == pytest.approx(0.25)

    def test_from_optimization_min_cost(self):
        w = WeightVector.from_optimization(OptimizationGoal.MIN_COST)
        assert w.cost > 0.5

    def test_from_optimization_min_time(self):
        w = WeightVector.from_optimization(OptimizationGoal.MIN_TIME)
        assert w.time > 0.5


class TestConstraint:

    def _make_journey(self, fare=15.0, duration=45.0, transfers=1):
        return Journey(
            journey_id="test",
            origin_lat=30.06, origin_lng=31.24,
            destination_lat=30.07, destination_lng=31.25,
            total_duration_minutes=duration,
            total_fare_egp=fare,
            transfers=transfers,
        )

    def test_lte_passes(self):
        j = self._make_journey(fare=15.0)
        c = Constraint(field="fare", operator="lte", value=20.0)
        assert c.evaluate(j) is True

    def test_lte_fails(self):
        j = self._make_journey(fare=25.0)
        c = Constraint(field="fare", operator="lte", value=20.0)
        assert c.evaluate(j) is False

    def test_gte(self):
        j = self._make_journey(duration=60.0)
        c = Constraint(field="duration", operator="gte", value=30.0)
        assert c.evaluate(j) is True

    def test_unknown_field_passes(self):
        j = self._make_journey()
        c = Constraint(field="nonexistent_field", operator="lte", value=10.0)
        assert c.evaluate(j) is True  # unknown -> don't filter


class TestIntent:

    def test_missing_fields_both(self):
        intent = Intent(query_type=QueryType.JOURNEY_REQUEST)
        assert "origin" in intent.missing_fields
        assert "destination" in intent.missing_fields

    def test_missing_only_destination(self):
        intent = Intent(
            query_type=QueryType.JOURNEY_REQUEST,
            origin="سموحة",
        )
        assert "destination" in intent.missing_fields
        assert "origin" not in intent.missing_fields

    def test_complete_journey(self):
        intent = Intent(
            query_type=QueryType.JOURNEY_REQUEST,
            origin="سموحة",
            destination="العصافرة",
        )
        assert intent.is_complete is True

    def test_weights_auto_synced(self):
        intent = Intent(
            query_type=QueryType.JOURNEY_REQUEST,
            origin="a", destination="b",
            optimization=OptimizationGoal.MIN_COST,
        )
        assert intent.weights.cost > 0.5

    def test_clean_location_strips_whitespace(self):
        intent = Intent(
            query_type=QueryType.JOURNEY_REQUEST,
            origin="  سموحة  ",
            destination="  العصافرة  ",
        )
        assert intent.origin == "سموحة"
        assert intent.destination == "العصافرة"

    def test_clean_location_empty_becomes_none(self):
        intent = Intent(
            query_type=QueryType.JOURNEY_REQUEST,
            origin="",
        )
        assert intent.origin is None

    def test_language_default_arabic(self):
        intent = Intent()
        assert intent.language == Language.ARABIC


class TestChatRequest:

    def test_valid(self):
        r = ChatRequest(message="عايز أروح", session_id="sess_001")
        assert r.message == "عايز أروح"

    def test_strips_whitespace(self):
        r = ChatRequest(message="  hello  ", session_id="s1")
        assert r.message == "hello"

    def test_collapses_spaces(self):
        r = ChatRequest(message="hello   world", session_id="s1")
        assert r.message == "hello world"

    def test_empty_message_fails(self):
        with pytest.raises(Exception):
            ChatRequest(message="", session_id="s1")