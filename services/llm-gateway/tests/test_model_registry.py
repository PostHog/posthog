import os
from unittest.mock import MagicMock, patch

import pytest

from llm_gateway.rate_limiting.model_cost_service import ModelCost, ModelCostService
from llm_gateway.services.model_registry import (
    ModelInfo,
    ModelRegistryService,
    _model_matches_allowlist,
    get_available_models,
    is_model_available,
)

PROVIDER_ENV_VARS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "FIREWORKS_API_KEY",
]

MOCK_COST_DATA: dict[str, ModelCost] = {
    "gpt-4o": {
        "litellm_provider": "openai",
        "max_input_tokens": 128000,
        "supports_vision": True,
        "mode": "chat",
    },
    "gpt-4o-mini": {
        "litellm_provider": "openai",
        "max_input_tokens": 128000,
        "supports_vision": True,
        "mode": "chat",
    },
    "gpt-5.2": {
        "litellm_provider": "openai",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "gpt-5-mini": {
        "litellm_provider": "openai",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "gpt-5.3-codex": {
        "litellm_provider": "openai",
        "max_input_tokens": 200000,
        "supports_vision": False,
        "mode": "chat",
    },
    "o1": {
        "litellm_provider": "openai",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "claude-3-5-sonnet-20241022": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "claude-haiku-4-5-20251001": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "claude-opus-4-5": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "claude-opus-4-6": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "claude-sonnet-4-5": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "claude-sonnet-4-6": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "claude-haiku-4-5": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "openrouter/anthropic/claude-3.5-sonnet": {
        "litellm_provider": "openrouter",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct": {
        "litellm_provider": "fireworks_ai",
        "max_input_tokens": 131072,
        "supports_vision": False,
        "mode": "chat",
    },
    "text-embedding-ada-002": {
        "litellm_provider": "openai",
        "max_input_tokens": 8191,
        "supports_vision": False,
        "mode": "embedding",
    },
}


def mock_get_costs(self: ModelCostService, model: str) -> ModelCost | None:
    return MOCK_COST_DATA.get(model)


def mock_get_all_models(self: ModelCostService) -> dict[str, ModelCost]:
    return MOCK_COST_DATA


def create_mock_settings(
    openai: bool = True,
    anthropic: bool = True,
    openrouter: bool = False,
    fireworks: bool = False,
) -> MagicMock:
    settings = MagicMock()
    settings.openai_api_key = "sk-test" if openai else None
    settings.anthropic_api_key = "sk-ant-test" if anthropic else None
    settings.openrouter_api_key = "or-test" if openrouter else None
    settings.fireworks_api_key = "fw-test" if fireworks else None
    return settings


@pytest.fixture(autouse=True)
def reset_services():
    ModelRegistryService.reset_instance()
    ModelCostService.reset_instance()
    yield
    ModelRegistryService.reset_instance()
    ModelCostService.reset_instance()


@pytest.fixture(autouse=True)
def mock_cost_service():
    with (
        patch.object(ModelCostService, "get_costs", mock_get_costs),
        patch.object(ModelCostService, "get_all_models", mock_get_all_models),
    ):
        yield


@pytest.fixture(autouse=True)
def clear_env_api_keys():
    """Prevent real API keys in CI from leaking into unit tests.

    _get_configured_providers() checks both settings and env vars, so we need
    to clear the env vars to ensure unit tests only reflect mock settings.
    """
    with patch.dict(os.environ, {}, clear=False):
        for var in PROVIDER_ENV_VARS:
            os.environ.pop(var, None)
        yield


@pytest.fixture(autouse=True)
def mock_settings():
    with patch(
        "llm_gateway.services.model_registry.get_settings",
        return_value=create_mock_settings(),
    ):
        yield


class TestModelRegistryService:
    def test_get_instance_returns_singleton(self):
        instance1 = ModelRegistryService.get_instance()
        instance2 = ModelRegistryService.get_instance()
        assert instance1 is instance2

    def test_reset_instance_clears_singleton(self):
        instance1 = ModelRegistryService.get_instance()
        ModelRegistryService.reset_instance()
        instance2 = ModelRegistryService.get_instance()
        assert instance1 is not instance2


class TestGetModel:
    @pytest.mark.parametrize(
        "model_id,expected_provider",
        [
            ("gpt-4o", "openai"),
            ("claude-sonnet-4-5", "anthropic"),
            ("openrouter/anthropic/claude-3.5-sonnet", "openrouter"),
            ("fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct", "fireworks_ai"),
        ],
    )
    def test_returns_model_info_for_known_model(self, model_id: str, expected_provider: str):
        service = ModelRegistryService.get_instance()
        model = service.get_model(model_id)
        assert model is not None
        assert model.id == model_id
        assert model.provider == expected_provider

    def test_returns_none_for_unknown_model(self):
        service = ModelRegistryService.get_instance()
        model = service.get_model("unknown-model")
        assert model is None


class TestGetAvailableModels:
    def test_returns_all_chat_models_from_configured_providers(self):
        models = get_available_models("llm_gateway")
        model_ids = {m.id for m in models}
        assert "gpt-4o" in model_ids
        assert "claude-sonnet-4-5" in model_ids
        assert "claude-3-5-sonnet-20241022" in model_ids
        # New providers not configured by default
        assert "openrouter/anthropic/claude-3.5-sonnet" not in model_ids
        assert "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct" not in model_ids

    def test_excludes_embedding_models(self):
        models = get_available_models("llm_gateway")
        model_ids = {m.id for m in models}
        assert "text-embedding-ada-002" not in model_ids

    def test_returns_model_info_objects(self):
        models = get_available_models("llm_gateway")
        assert all(isinstance(m, ModelInfo) for m in models)


class TestProviderFiltering:
    def test_only_returns_models_from_configured_providers(self):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(openai=True, anthropic=False),
        ):
            models = get_available_models("llm_gateway")
            providers = {m.provider for m in models}
            assert providers == {"openai"}
            model_ids = {m.id for m in models}
            assert "gpt-4o" in model_ids
            assert "claude-sonnet-4-5" not in model_ids

    def test_returns_empty_when_no_providers_configured(self):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(openai=False, anthropic=False),
        ):
            models = get_available_models("llm_gateway")
            assert len(models) == 0

    def test_returns_multiple_providers_when_configured(self):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(openai=True, anthropic=True),
        ):
            models = get_available_models("llm_gateway")
            providers = {m.provider for m in models}
            assert providers == {"openai", "anthropic"}

    @pytest.mark.parametrize(
        "provider_kwargs,expected_provider,expected_model_id",
        [
            (
                {"openai": False, "anthropic": False, "openrouter": True},
                "openrouter",
                "openrouter/anthropic/claude-3.5-sonnet",
            ),
            (
                {"openai": False, "anthropic": False, "fireworks": True},
                "fireworks_ai",
                "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct",
            ),
        ],
    )
    def test_returns_single_new_provider_models_when_configured(
        self, provider_kwargs, expected_provider, expected_model_id
    ):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(**provider_kwargs),
        ):
            models = get_available_models("llm_gateway")
            providers = {m.provider for m in models}
            assert providers == {expected_provider}
            model_ids = {m.id for m in models}
            assert expected_model_id in model_ids

    def test_returns_all_four_providers_when_configured(self):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(openai=True, anthropic=True, openrouter=True, fireworks=True),
        ):
            models = get_available_models("llm_gateway")
            providers = {m.provider for m in models}
            assert providers == {"openai", "anthropic", "openrouter", "fireworks_ai"}


class TestModelMatchesAllowlist:
    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("gpt-4o", True),
            ("GPT-4O", True),
            ("Gpt-4o", True),
            ("claude-sonnet-4-5", True),
            ("CLAUDE-SONNET-4-5", True),
            ("unknown-model", False),
            ("gpt-4o-extra", False),
        ],
    )
    def test_case_insensitive_exact_matching(self, model_id: str, expected: bool):
        allowlist = frozenset({"gpt-4o", "claude-sonnet-4-5"})
        assert _model_matches_allowlist(model_id, allowlist) == expected


class TestIsModelAvailable:
    @pytest.mark.parametrize(
        "model_id,product,expected",
        [
            ("gpt-4o", "llm_gateway", True),
            ("gpt-4o", "posthog_code", False),
            ("o1", "llm_gateway", True),
            ("o1", "posthog_code", False),
            ("claude-opus-4-6", "posthog_code", True),
            ("gpt-5.3-codex", "posthog_code", True),
            ("gpt-5.2", "posthog_code", True),
            ("gpt-5-mini", "posthog_code", True),
            ("claude-opus-4-5", "posthog_code", True),
            ("claude-sonnet-4-5", "posthog_code", True),
            ("claude-haiku-4-5", "posthog_code", True),
            # New providers not configured by default
            ("openrouter/anthropic/claude-3.5-sonnet", "llm_gateway", False),
            ("fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct", "llm_gateway", False),
            ("unknown-model", "llm_gateway", False),
            # Legacy aliases still work
            ("gpt-4o", "twig", False),
            ("claude-opus-4-6", "twig", True),
            ("gpt-4o", "array", False),
            ("claude-opus-4-5", "array", True),
        ],
    )
    def test_model_availability(self, model_id: str, product: str, expected: bool):
        assert is_model_available(model_id, product) == expected

    def test_model_not_available_when_provider_not_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            for var in PROVIDER_ENV_VARS:
                os.environ.pop(var, None)
            with patch(
                "llm_gateway.services.model_registry.get_settings",
                return_value=create_mock_settings(openai=False, anthropic=True),
            ):
                assert is_model_available("gpt-4o", "llm_gateway") is False
                assert is_model_available("claude-sonnet-4-5", "llm_gateway") is True
