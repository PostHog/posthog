from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import litellm
import pytest

from llm_gateway.rate_limiting.cost_refresh import CostRefreshService
from llm_gateway.rate_limiting.model_cost_service import ModelCostService


@pytest.fixture(autouse=True)
def restore_litellm_globals() -> Iterator[None]:
    # refresh() mutates litellm globals — snapshot and restore so tests don't leak.
    snapshot = (
        litellm.model_cost,
        litellm.anthropic_models.copy(),
        litellm.open_ai_chat_completion_models.copy(),
    )
    try:
        yield
    finally:
        litellm.model_cost, anthropic, openai = snapshot
        litellm.anthropic_models.clear()
        litellm.anthropic_models.update(anthropic)
        litellm.open_ai_chat_completion_models.clear()
        litellm.open_ai_chat_completion_models.update(openai)


class TestCostRefreshService:
    @pytest.fixture(autouse=True)
    def reset_singleton(self) -> Iterator[None]:
        CostRefreshService.reset_instance()
        yield
        CostRefreshService.reset_instance()

    def test_singleton_pattern(self) -> None:
        instance1 = CostRefreshService.get_instance()
        instance2 = CostRefreshService.get_instance()
        assert instance1 is instance2

    def test_reset_instance_clears_singleton(self) -> None:
        instance1 = CostRefreshService.get_instance()
        CostRefreshService.reset_instance()
        instance2 = CostRefreshService.get_instance()
        assert instance1 is not instance2

    @patch("llm_gateway.rate_limiting.cost_refresh.get_model_cost_map")
    def test_refresh_updates_litellm_model_cost(self, mock_get_cost_map: MagicMock) -> None:
        mock_costs = {
            "gpt-4": {"input_cost_per_token": 0.00003, "output_cost_per_token": 0.00006},
            "claude-3-opus": {"input_cost_per_token": 0.000015, "output_cost_per_token": 0.000075},
        }
        mock_get_cost_map.return_value = mock_costs

        CostRefreshService.get_instance().refresh()

        assert litellm.model_cost == mock_costs
        mock_get_cost_map.assert_called_once()

    @patch("llm_gateway.rate_limiting.cost_refresh.litellm.add_known_models")
    @patch("llm_gateway.rate_limiting.cost_refresh.get_model_cost_map")
    def test_refresh_registers_provider_models(
        self,
        mock_get_cost_map: MagicMock,
        mock_add_known_models: MagicMock,
    ) -> None:
        # The provider sets (anthropic_models, etc.) back get_llm_provider's inference,
        # so we must re-register them on every refresh — otherwise the sets stay frozen
        # at import time and freshly added models raise "LLM Provider NOT provided".
        mock_costs = {"some-model": {"litellm_provider": "anthropic"}}
        mock_get_cost_map.return_value = mock_costs

        CostRefreshService.get_instance().refresh()

        mock_add_known_models.assert_called_once_with(mock_costs)

    @patch("llm_gateway.rate_limiting.cost_refresh.get_model_cost_map")
    def test_ensure_fresh_skips_refresh_within_ttl(self, mock_get_cost_map: MagicMock) -> None:
        mock_get_cost_map.return_value = {}

        service = CostRefreshService.get_instance()
        service.ensure_fresh()
        service.ensure_fresh()
        service.ensure_fresh()

        mock_get_cost_map.assert_called_once()

    @patch("llm_gateway.rate_limiting.cost_refresh.get_model_cost_map")
    @patch("llm_gateway.rate_limiting.cost_refresh.time.monotonic")
    def test_ensure_fresh_refreshes_after_ttl(self, mock_time: MagicMock, mock_get_cost_map: MagicMock) -> None:
        mock_get_cost_map.return_value = {}
        mock_time.return_value = 0

        service = CostRefreshService.get_instance()
        service.ensure_fresh()
        assert mock_get_cost_map.call_count == 1

        mock_time.return_value = 301
        service.ensure_fresh()
        assert mock_get_cost_map.call_count == 2

    @patch("llm_gateway.rate_limiting.cost_refresh.get_model_cost_map")
    def test_refresh_handles_exception_gracefully(self, mock_get_cost_map: MagicMock) -> None:
        mock_get_cost_map.side_effect = Exception("Network error")

        service = CostRefreshService.get_instance()
        service.refresh()

    @patch("llm_gateway.rate_limiting.cost_refresh.get_model_cost_map")
    def test_refresh_on_startup_called_in_ensure_fresh(self, mock_get_cost_map: MagicMock) -> None:
        mock_get_cost_map.return_value = {"model": {}}

        service = CostRefreshService.get_instance()
        assert service._last_refresh == 0

        service.ensure_fresh()
        assert service._last_refresh > 0


class TestModelCostServiceRefresh:
    @pytest.fixture(autouse=True)
    def reset_singleton(self) -> Iterator[None]:
        ModelCostService.reset_instance()
        yield
        ModelCostService.reset_instance()

    @patch("llm_gateway.rate_limiting.model_cost_service.litellm.add_known_models")
    @patch("llm_gateway.rate_limiting.model_cost_service.get_model_cost_map")
    def test_refresh_registers_provider_models(
        self,
        mock_get_cost_map: MagicMock,
        mock_add_known_models: MagicMock,
    ) -> None:
        # Same contract as CostRefreshService — _refresh_cache must keep the
        # provider sets in sync with the freshly fetched cost map.
        mock_costs = {"some-model": {"litellm_provider": "anthropic"}}
        mock_get_cost_map.return_value = mock_costs

        ModelCostService.get_instance()._refresh_cache()

        mock_add_known_models.assert_called_once_with(mock_costs)
