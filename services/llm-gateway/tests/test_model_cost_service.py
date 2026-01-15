from typing import Any
from unittest.mock import patch

import litellm
import pytest

from llm_gateway.rate_limiting.model_cost_service import (
    CACHE_TTL_SECONDS,
    DEFAULT_LIMITS,
    ModelCostService,
    get_model_costs,
    get_model_limits,
)

MOCK_MODEL_COSTS: dict[str, Any] = {
    "claude-3-5-haiku-20241022": {
        "input_cost_per_token": 0.0000008,
        "output_cost_per_token": 0.000004,
        "max_input_tokens": 200000,
        "max_output_tokens": 8192,
        "litellm_provider": "anthropic",
    },
    "gpt-4o-mini": {
        "input_cost_per_token": 0.00000015,
        "output_cost_per_token": 0.0000006,
        "max_input_tokens": 128000,
        "max_output_tokens": 16384,
        "litellm_provider": "openai",
    },
}


@pytest.fixture(autouse=True)
def reset_model_cost_service():
    ModelCostService.reset_instance()
    yield
    ModelCostService.reset_instance()


class TestModelCostService:
    def test_returns_defaults_for_unknown_model(self) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=MOCK_MODEL_COSTS,
        ):
            limits = get_model_limits("unknown-model-xyz")
        assert limits == DEFAULT_LIMITS

    def test_caches_limits(self) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=MOCK_MODEL_COSTS,
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

    def test_get_model_costs_returns_none_for_unknown(self) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=MOCK_MODEL_COSTS,
        ):
            costs = get_model_costs("unknown-model-xyz")
        assert costs is None

    def test_refreshes_cache_after_ttl_expires(self) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=MOCK_MODEL_COSTS,
        ):
            service = ModelCostService.get_instance()
            service._refresh_cache()
            initial_refresh = service._last_refresh

            with patch("llm_gateway.rate_limiting.model_cost_service.time.monotonic") as mock_time:
                mock_time.return_value = initial_refresh + CACHE_TTL_SECONDS + 1
                get_model_limits("claude-3-5-haiku-20241022")
                assert service._last_refresh != initial_refresh

    def test_keeps_existing_cache_on_refresh_error(self) -> None:
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=MOCK_MODEL_COSTS,
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

    def test_updates_litellm_model_cost_on_refresh(self) -> None:
        original_cost = litellm.model_cost.copy()
        with patch(
            "llm_gateway.rate_limiting.model_cost_service.get_model_cost_map",
            return_value=MOCK_MODEL_COSTS,
        ):
            service = ModelCostService.get_instance()
            service._refresh_cache()

        assert litellm.model_cost is not original_cost
        assert "claude-3-5-haiku-20241022" in litellm.model_cost
