from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest

from llm_gateway.rate_limiting.cost_refresh import (
    COST_ALIASES,
    CostRefreshService,
    apply_cost_aliases,
    normalize_metric_labels,
)
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


class TestApplyCostAliases:
    def test_adds_alias_when_canonical_present(self) -> None:
        cost: dict[str, Any] = {
            "moonshot/kimi-k2.6": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002},
        }
        apply_cost_aliases(cost)
        assert cost["openai/@cf/moonshotai/kimi-k2.6"] == cost["moonshot/kimi-k2.6"]
        # Load-bearing: the alias must be a copy, not a shared reference — otherwise an
        # in-place mutation under one key silently mutates the other.
        assert cost["openai/@cf/moonshotai/kimi-k2.6"] is not cost["moonshot/kimi-k2.6"]

    def test_does_not_overwrite_existing_alias(self) -> None:
        cost: dict[str, Any] = {
            "moonshot/kimi-k2.6": {"input_cost_per_token": 0.001},
            "openai/@cf/moonshotai/kimi-k2.6": {"input_cost_per_token": 0.999},
        }
        apply_cost_aliases(cost)
        assert cost["openai/@cf/moonshotai/kimi-k2.6"]["input_cost_per_token"] == 0.999

    @patch.dict(
        "llm_gateway.rate_limiting.cost_refresh.COST_ALIASES",
        {"openai/@cf/moonshotai/kimi-k2.6": "moonshot/kimi-k2.6"},
        clear=True,
    )
    @patch("llm_gateway.rate_limiting.cost_refresh.logger")
    def test_warns_when_canonical_missing(self, mock_logger: MagicMock) -> None:
        cost: dict[str, Any] = {"gpt-4o": {}}
        apply_cost_aliases(cost)
        assert "openai/@cf/moonshotai/kimi-k2.6" not in cost
        mock_logger.warning.assert_called_once_with(
            "cost_alias_canonical_missing",
            alias="openai/@cf/moonshotai/kimi-k2.6",
            canonical="moonshot/kimi-k2.6",
        )

    @patch.dict(
        "llm_gateway.rate_limiting.cost_refresh.COST_ALIASES",
        {"openai/@cf/moonshotai/kimi-k2.6": "moonshot/kimi-k2.6"},
        clear=True,
    )
    @patch("llm_gateway.rate_limiting.cost_refresh.logger")
    def test_does_not_warn_when_alias_already_present(self, mock_logger: MagicMock) -> None:
        cost: dict[str, Any] = {"openai/@cf/moonshotai/kimi-k2.6": {"input_cost_per_token": 0.999}}
        apply_cost_aliases(cost)
        mock_logger.warning.assert_not_called()

    def test_canonicals_exist_in_litellm_cost_map(self) -> None:
        """Lock in that every COST_ALIASES canonical is present in the pinned litellm
        cost map. If a litellm bump drops the canonical, this fails in CI rather than
        letting `apply_cost_aliases` log `cost_alias_canonical_missing` every refresh
        in production and falling back to the default cost for those models.
        """
        missing = [canonical for canonical in COST_ALIASES.values() if canonical not in litellm.model_cost]
        assert not missing, f"COST_ALIASES canonicals missing from litellm.model_cost: {missing}"


class TestNormalizeMetricLabels:
    def test_returns_user_facing_labels_for_aliased_model(self) -> None:
        provider, model = normalize_metric_labels("openai/@cf/moonshotai/kimi-k2.6", "openai")
        assert provider == "cloudflare"
        assert model == "@cf/moonshotai/kimi-k2.6"

    def test_passes_through_unaliased_model(self) -> None:
        provider, model = normalize_metric_labels("gpt-4o", "openai")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_passes_through_unknown_model(self) -> None:
        provider, model = normalize_metric_labels("unknown", "unknown")
        assert provider == "unknown"
        assert model == "unknown"


class TestModelCostServiceAliases:
    @pytest.fixture(autouse=True)
    def reset_singleton(self) -> Iterator[None]:
        ModelCostService.reset_instance()
        yield
        ModelCostService.reset_instance()

    @patch("llm_gateway.rate_limiting.model_cost_service.get_model_cost_map")
    def test_refresh_cache_applies_cost_aliases(self, mock_get_cost_map: MagicMock) -> None:
        mock_get_cost_map.return_value = {
            "moonshot/kimi-k2.6": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002},
        }
        service = ModelCostService.get_instance()
        cost_for_alias = service.get_costs("openai/@cf/moonshotai/kimi-k2.6")

        assert cost_for_alias == {"input_cost_per_token": 0.001, "output_cost_per_token": 0.002}
        assert "openai/@cf/moonshotai/kimi-k2.6" in litellm.model_cost


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
