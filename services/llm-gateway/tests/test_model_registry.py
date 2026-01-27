import os
from unittest.mock import MagicMock, patch

import pytest

from llm_gateway.rate_limiting.model_cost_service import ModelCost, ModelCostService
from llm_gateway.services.model_registry import (
    ModelInfo,
    ModelRegistryService,
    get_available_models,
    is_model_available,
)

PROVIDER_ENV_VARS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]

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
    "claude-3-5-haiku-20241022": {
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
    "claude-sonnet-4-5": {
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
    "gemini-2.0-flash": {
        "litellm_provider": "vertex_ai",
        "max_input_tokens": 1048576,
        "supports_vision": True,
        "mode": "chat",
    },
    "gemini-1.5-pro": {
        "litellm_provider": "vertex_ai",
        "max_input_tokens": 2097152,
        "supports_vision": True,
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
    gemini: bool = True,
) -> MagicMock:
    settings = MagicMock()
    settings.openai_api_key = "sk-test" if openai else None
    settings.anthropic_api_key = "sk-ant-test" if anthropic else None
    settings.gemini_api_key = "gemini-test" if gemini else None
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
            ("claude-3-5-sonnet-20241022", "anthropic"),
            ("gemini-2.0-flash", "vertex_ai"),
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
        assert "claude-3-5-sonnet-20241022" in model_ids
        assert "gemini-2.0-flash" in model_ids

    def test_excludes_embedding_models(self):
        models = get_available_models("llm_gateway")
        model_ids = {m.id for m in models}
        assert "text-embedding-ada-002" not in model_ids

    def test_returns_model_info_objects(self):
        models = get_available_models("llm_gateway")
        assert all(isinstance(m, ModelInfo) for m in models)


class TestProviderFiltering:
    @pytest.fixture(autouse=True)
    def clear_env_api_keys(self):
        with patch.dict(os.environ, {}, clear=False):
            for var in PROVIDER_ENV_VARS:
                os.environ.pop(var, None)
            yield

    def test_only_returns_models_from_configured_providers(self):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(openai=True, anthropic=False, gemini=False),
        ):
            models = get_available_models("llm_gateway")
            providers = {m.provider for m in models}
            assert providers == {"openai"}
            model_ids = {m.id for m in models}
            assert "gpt-4o" in model_ids
            assert "claude-3-5-sonnet-20241022" not in model_ids
            assert "gemini-2.0-flash" not in model_ids

    def test_returns_empty_when_no_providers_configured(self):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(openai=False, anthropic=False, gemini=False),
        ):
            models = get_available_models("llm_gateway")
            assert len(models) == 0

    def test_returns_multiple_providers_when_configured(self):
        with patch(
            "llm_gateway.services.model_registry.get_settings",
            return_value=create_mock_settings(openai=True, anthropic=True, gemini=False),
        ):
            models = get_available_models("llm_gateway")
            providers = {m.provider for m in models}
            assert providers == {"openai", "anthropic"}


class TestIsModelAvailable:
    @pytest.mark.parametrize(
        "model_id,product,expected",
        [
            ("gpt-4o", "llm_gateway", True),
            ("gpt-4o", "twig", False),
            ("o1", "llm_gateway", True),
            ("o1", "array", False),
            ("gpt-5.2", "array", True),
            ("gpt-5-mini", "twig", True),
            ("claude-opus-4-5", "array", True),
            ("claude-sonnet-4-5", "array", True),
            ("claude-haiku-4-5", "array", True),
            ("unknown-model", "llm_gateway", False),
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
                return_value=create_mock_settings(openai=False, anthropic=True, gemini=True),
            ):
                assert is_model_available("gpt-4o", "llm_gateway") is False
                assert is_model_available("claude-3-5-sonnet-20241022", "llm_gateway") is True
