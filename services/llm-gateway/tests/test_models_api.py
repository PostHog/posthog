from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from llm_gateway.rate_limiting.model_cost_service import ModelCost, ModelCostService
from llm_gateway.services.model_registry import ModelRegistryService

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
    "gemini-2.0-flash": {
        "litellm_provider": "vertex_ai",
        "max_input_tokens": 1048576,
        "supports_vision": True,
        "mode": "chat",
    },
}


def mock_get_costs(self: ModelCostService, model: str) -> ModelCost | None:
    return MOCK_COST_DATA.get(model)


def mock_get_all_models(self: ModelCostService) -> dict[str, ModelCost]:
    return MOCK_COST_DATA


def create_mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.openai_api_key = "sk-test"
    settings.anthropic_api_key = "sk-ant-test"
    settings.gemini_api_key = "gemini-test"
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


class TestListModelsEndpoint:
    def test_returns_models_list(self, client: TestClient):
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

    def test_model_object_has_required_fields(self, client: TestClient):
        response = client.get("/v1/models")
        data = response.json()
        model = data["data"][0]
        assert "id" in model
        assert "object" in model
        assert model["object"] == "model"
        assert "created" in model
        assert "owned_by" in model
        assert "context_window" in model
        assert "supports_streaming" in model
        assert "supports_vision" in model


class TestListModelsForProductEndpoint:
    def test_returns_models_for_llm_gateway(self, client: TestClient):
        response = client.get("/llm_gateway/v1/models")
        assert response.status_code == 200
        data = response.json()
        model_ids = {m["id"] for m in data["data"]}
        assert "gpt-4o" in model_ids
        assert "o1" in model_ids

    def test_array_returns_all_models_from_configured_providers(self, client: TestClient):
        response = client.get("/array/v1/models")
        assert response.status_code == 200
        data = response.json()
        model_ids = {m["id"] for m in data["data"]}
        assert "gpt-4o" in model_ids
        assert "o1" in model_ids
        assert "claude-3-5-sonnet-20241022" in model_ids
        assert "gemini-2.0-flash" in model_ids

    def test_returns_error_for_invalid_product(self, client: TestClient):
        response = client.get("/invalid_product/v1/models")
        assert response.status_code == 400
        assert "Invalid product" in response.json()["detail"]
