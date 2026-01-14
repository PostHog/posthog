from typing import Any
from unittest.mock import patch

import litellm
import pytest
from litellm import model_cost_map_url
from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map

from llm_gateway.rate_limiting.model_cost_service import (
    CACHE_TTL_SECONDS,
    DEFAULT_LIMITS,
    TARGET_LIMIT_COST_PER_HOUR,
    ModelCostService,
    get_model_costs,
    get_model_limits,
)


@pytest.fixture(scope="module")
def litellm_costs() -> dict[str, Any]:
    return get_model_cost_map(url=model_cost_map_url)


@pytest.fixture(autouse=True)
def reset_model_cost_service():
    ModelCostService.reset_instance()
    yield
    ModelCostService.reset_instance()


class TestModelCostService:
    def test_calculates_limits_from_litellm_cost(self, litellm_costs: dict[str, Any]) -> None:
        model = "claude-3-5-haiku-20241022"
        cost = litellm_costs.get(model)
        assert cost is not None
        assert cost["input_cost_per_token"] > 0
        assert cost["output_cost_per_token"] > 0

        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            limits = get_model_limits(model)

        expected_input = int(TARGET_LIMIT_COST_PER_HOUR / cost["input_cost_per_token"])
        expected_output = int(TARGET_LIMIT_COST_PER_HOUR / cost["output_cost_per_token"])
        assert limits["input_tph"] == expected_input
        assert limits["output_tph"] == expected_output
        assert limits["input_tph"] > 0
        assert limits["output_tph"] > 0
        assert limits["input_tph"] >= limits["output_tph"]  # Input is cheaper than output

    def test_returns_defaults_for_unknown_model(self, litellm_costs: dict[str, Any]) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            limits = get_model_limits("unknown-model-xyz")
        assert limits == DEFAULT_LIMITS

    def test_caches_limits(self, litellm_costs: dict[str, Any]) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            service = ModelCostService.get_instance()
            service._refresh_cache()
            initial_refresh = service._last_refresh

            get_model_limits("claude-3-5-haiku-20241022")
            assert service._last_refresh == initial_refresh

    def test_singleton_instance(self) -> None:
        instance1 = ModelCostService.get_instance()
        instance2 = ModelCostService.get_instance()
        assert instance1 is instance2

    def test_get_model_costs_returns_cost_data(self, litellm_costs: dict[str, Any]) -> None:
        model = "claude-3-5-haiku-20241022"
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            costs = get_model_costs(model)
        assert costs is not None
        assert costs["input_cost_per_token"] > 0
        assert costs["output_cost_per_token"] > 0

    def test_get_model_costs_returns_none_for_unknown(self, litellm_costs: dict[str, Any]) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            costs = get_model_costs("unknown-model-xyz")
        assert costs is None

    def test_refreshes_cache_after_ttl_expires(self, litellm_costs: dict[str, Any]) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            service = ModelCostService.get_instance()
            service._refresh_cache()
            initial_refresh = service._last_refresh

            with patch("llm_gateway.rate_limiting.model_cost_service.time.monotonic") as mock_time:
                mock_time.return_value = initial_refresh + CACHE_TTL_SECONDS + 1
                get_model_limits("claude-3-5-haiku-20241022")
                assert service._last_refresh != initial_refresh

    def test_keeps_existing_cache_on_refresh_error(self, litellm_costs: dict[str, Any]) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            service = ModelCostService.get_instance()
            service._refresh_cache()
            cached_limits = service._limits.copy()

        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            side_effect=Exception("Network error"),
        ):
            service._refresh_cache()

        assert service._limits == cached_limits

    def test_updates_litellm_model_cost_on_refresh(self, litellm_costs: dict[str, Any]) -> None:
        original_cost = litellm.model_cost.copy()
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=litellm_costs,
        ):
            service = ModelCostService.get_instance()
            service._refresh_cache()

        assert litellm.model_cost is not original_cost
        assert "claude-3-5-haiku-20241022" in litellm.model_cost
