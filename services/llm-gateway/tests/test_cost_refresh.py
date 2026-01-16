from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llm_gateway.rate_limiting.cost_refresh import CostRefreshService


class TestCostRefreshService:
    @pytest.fixture(autouse=True)
    def reset_singleton(self) -> None:
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
        import litellm

        mock_costs = {
            "gpt-4": {"input_cost_per_token": 0.00003, "output_cost_per_token": 0.00006},
            "claude-3-opus": {"input_cost_per_token": 0.000015, "output_cost_per_token": 0.000075},
        }
        mock_get_cost_map.return_value = mock_costs

        service = CostRefreshService.get_instance()
        service.refresh()

        assert litellm.model_cost == mock_costs
        mock_get_cost_map.assert_called_once()

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
