"""
test_config.py
Tests config loads correctly and routing bounds are enforced.
"""
 

import pytest
from config import get_settings, AppSettings


class TestConfig:

    def test_settings_loads(self):
        s = get_settings()
        assert s is not None

    def test_singleton(self):
        assert get_settings() is get_settings()

    def test_db_dsn(self):
        s = get_settings()
        assert s.db.dsn.startswith("postgresql://")

    def test_routing_url_is_azure(self):
        s = get_settings()
        assert "azurewebsites" in s.routing.engine_url or \
               "localhost" in s.routing.engine_url

    def test_routing_url_helpers(self):
        s = get_settings()
        assert s.routing.routes_url.endswith("/api/routes")
        assert s.routing.health_url.endswith("/api/health")

    # API bounds tests  

    def test_max_transfers_default_in_range(self):
        s = get_settings()
        assert 0 <= s.routing.max_transfers <= 5

    def test_walking_cutoff_default_in_range(self):
        s = get_settings()
        assert 100 <= s.routing.walking_cutoff <= 5000

    def test_top_k_default_in_range(self):
        s = get_settings()
        assert 1 <= s.routing.top_k <= 20

    def test_clamp_params_over_max(self):
        s = get_settings()
        result = s.routing.clamp_params(
            max_transfers=99,    # over max=5
            walking_cutoff=9999, # over max=5000
            top_k=100,           # over max=20
        )
        assert result["max_transfers"]  == 5
        assert result["walking_cutoff"] == 5000
        assert result["top_k"]          == 20

    def test_clamp_params_under_min(self):
        s = get_settings()
        result = s.routing.clamp_params(
            max_transfers=0,   # valid (min=0)
            walking_cutoff=50, # under min=100
            top_k=0,           # under min=1
        )
        assert result["max_transfers"]  == 0
        assert result["walking_cutoff"] == 100
        assert result["top_k"]          == 1

    def test_clamp_params_valid(self):
        s = get_settings()
        result = s.routing.clamp_params(
            max_transfers=2,
            walking_cutoff=1000,
            top_k=5,
        )
        assert result["max_transfers"]  == 2
        assert result["walking_cutoff"] == 1000
        assert result["top_k"]          == 5

    def test_summary_contains_correct_ranges(self):
        s = get_settings()
        summary = s.summary()
        assert "API max: 20" in summary
        assert "API max: 5" in summary
        assert "100-5000" in summary


class TestRoutingEngineSettings:

    def test_invalid_max_transfers_raises(self):
        from config import RoutingEngineSettings
        with pytest.raises(Exception):
            RoutingEngineSettings(
                ROUTING_MAX_TRANSFERS=6  # over API max of 5
            )

    def test_invalid_walking_cutoff_raises(self):
        from config import RoutingEngineSettings
        with pytest.raises(Exception):
            RoutingEngineSettings(
                ROUTING_WALKING_CUTOFF=50  # under API min of 100
            )

    def test_invalid_top_k_raises(self):
        from config import RoutingEngineSettings
        with pytest.raises(Exception):
            RoutingEngineSettings(
                ROUTING_TOP_K=21  # over API max of 20
            )