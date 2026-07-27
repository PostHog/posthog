from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import litellm
import pytest

from llm_gateway.rate_limiting.model_cost_overrides import (
    MODEL_COST_OVERRIDES,
    apply_model_cost_overrides,
)
from llm_gateway.rate_limiting.model_cost_service import ModelCost, ModelCostService
from llm_gateway.services.model_registry import (
    ModelRegistryService,
    get_available_models,
)

PROVIDER_ENV_VARS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "FIREWORKS_API_KEY",
]


class TestApplyModelCostOverrides:
    @pytest.mark.parametrize("model_id", sorted(MODEL_COST_OVERRIDES))
    def test_adds_missing_model(self, model_id: str) -> None:
        cost_map: dict[str, ModelCost] = {"gpt-4": {"litellm_provider": "openai"}}
        apply_model_cost_overrides(cost_map)
        assert cost_map[model_id] == MODEL_COST_OVERRIDES[model_id]

    @pytest.mark.parametrize("model_id", sorted(MODEL_COST_OVERRIDES))
    def test_does_not_override_existing_upstream_entry(self, model_id: str) -> None:
        upstream: ModelCost = {"litellm_provider": "anthropic", "max_input_tokens": 1_000_000}
        cost_map: dict[str, ModelCost] = {model_id: upstream}
        apply_model_cost_overrides(cost_map)
        assert cost_map[model_id] is upstream

    def test_returns_same_object_in_place(self) -> None:
        cost_map: dict[str, ModelCost] = {}
        assert apply_model_cost_overrides(cost_map) is cost_map

    @pytest.mark.parametrize("model_id", sorted(MODEL_COST_OVERRIDES))
    def test_inserted_entry_is_a_copy(self, model_id: str) -> None:
        # The shared constant must survive callers (and litellm) mutating the map.
        cost_map: dict[str, ModelCost] = {}
        apply_model_cost_overrides(cost_map)
        cost_map[model_id]["input_cost_per_token"] = -1.0
        assert MODEL_COST_OVERRIDES[model_id].get("input_cost_per_token") != -1.0


class TestOverrideSurfacesThroughRefresh:
    @pytest.fixture(autouse=True)
    def restore_litellm_globals(self) -> Iterator[None]:
        model_cost_snapshot = litellm.model_cost
        # add_known_models mutates one provider set per provider in the cost map,
        # so snapshot every set in litellm's namespace rather than just anthropic's.
        set_snapshots = {name: value.copy() for name, value in vars(litellm).items() if isinstance(value, set)}
        try:
            yield
        finally:
            litellm.model_cost = model_cost_snapshot
            for name, snapshot in set_snapshots.items():
                provider_set = getattr(litellm, name)
                provider_set.clear()
                provider_set.update(snapshot)

    @pytest.fixture(autouse=True)
    def reset_singletons(self) -> Iterator[None]:
        ModelCostService.reset_instance()
        ModelRegistryService.reset_instance()
        yield
        ModelCostService.reset_instance()
        ModelRegistryService.reset_instance()

    @patch("llm_gateway.rate_limiting.model_cost_service.get_model_cost_map")
    def test_refresh_injects_fable_5_when_upstream_missing(self, mock_get_cost_map: MagicMock) -> None:
        mock_get_cost_map.return_value = {
            "claude-opus-4-8": {
                "litellm_provider": "anthropic",
                "mode": "chat",
                "max_input_tokens": 200_000,
            },
        }

        service = ModelCostService.get_instance()
        service._refresh_cache()

        costs = service.get_costs("claude-fable-5")
        assert costs is not None
        assert costs["litellm_provider"] == "anthropic"
        assert "claude-fable-5" in service.get_all_models()

    @patch("llm_gateway.rate_limiting.model_cost_service.get_model_cost_map")
    def test_fable_5_listed_for_posthog_code(self, mock_get_cost_map: MagicMock) -> None:
        mock_get_cost_map.return_value = {
            "claude-opus-4-8": {
                "litellm_provider": "anthropic",
                "mode": "chat",
                "max_input_tokens": 200_000,
            },
        }
        ModelCostService.get_instance()._refresh_cache()

        settings = MagicMock()
        settings.openai_api_key = None
        settings.anthropic_api_key = "sk-ant-test"
        settings.openrouter_api_key = None
        settings.fireworks_api_key = None

        with patch.dict(os.environ, {}, clear=False):
            for var in PROVIDER_ENV_VARS:
                os.environ.pop(var, None)
            with patch(
                "llm_gateway.services.model_registry.get_settings",
                return_value=settings,
            ):
                model_ids = {m.id for m in get_available_models("posthog_code")}

        assert "claude-opus-4-8" in model_ids
        assert "claude-fable-5" in model_ids
