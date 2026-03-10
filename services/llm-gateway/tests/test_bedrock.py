from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

MOCK_BEDROCK_MODELS = {
    "bedrock/anthropic.claude-opus-4-5-20250929-v1:0": {
        "litellm_provider": "bedrock",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "bedrock/anthropic.claude-opus-4-6-v1:0": {
        "litellm_provider": "bedrock",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0": {
        "litellm_provider": "bedrock",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "bedrock/anthropic.claude-sonnet-4-6-v1:0": {
        "litellm_provider": "bedrock",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
    "bedrock/anthropic.claude-haiku-4-5-20251001-v1:0": {
        "litellm_provider": "bedrock",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
    },
}


@pytest.fixture(autouse=True)
def mock_bedrock_cost_map() -> None:
    with patch("llm_gateway.api.bedrock.ModelCostService.get_all_models", return_value=MOCK_BEDROCK_MODELS):
        yield


class TestBedrockMessagesEndpoint:
    @pytest.fixture
    def valid_request_body(self) -> dict[str, Any]:
        return {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture
    def mock_anthropic_response(self) -> dict[str, Any]:
        return {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    @patch("llm_gateway.api.bedrock_router.get_settings")
    @patch("llm_gateway.api.bedrock_router.litellm.anthropic_messages")
    def test_maps_anthropic_model_to_bedrock(
        self,
        mock_anthropic: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        mock_anthropic_response: dict,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_get_settings.return_value = mock_settings

        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_anthropic_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/bedrock/v1/messages",
            json={"model": "claude-sonnet-4-5", "messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        call_kwargs = mock_anthropic.call_args.kwargs
        assert call_kwargs["model"] == "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert call_kwargs["aws_region_name"] == "us-east-1"

    @patch("llm_gateway.api.bedrock_router.get_settings")
    @patch("llm_gateway.api.bedrock_router.litellm.anthropic_messages")
    def test_product_route_supported(
        self,
        mock_anthropic: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        mock_anthropic_response: dict,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_get_settings.return_value = mock_settings

        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_anthropic_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/wizard/bedrock/v1/messages",
            json={"model": "claude-sonnet-4-5", "messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer phx_test_key"},
        )
        assert response.status_code == 200

    @patch("llm_gateway.api.bedrock_router.get_settings")
    def test_requires_bedrock_region(
        self,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = None
        mock_get_settings.return_value = mock_settings

        response = authenticated_client.post(
            "/bedrock/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 503
        assert "Bedrock region not configured" in response.json()["error"]["message"]

    @patch("llm_gateway.api.bedrock_router.get_settings")
    def test_unmapped_model_returns_400(
        self,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_get_settings.return_value = mock_settings

        response = authenticated_client.post(
            "/bedrock/v1/messages",
            json={"model": "claude-3-haiku-20240307", "messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert "is not available on Bedrock Anthropic routing" in response.json()["error"]["message"]


class TestBedrockCountTokensEndpoint:
    @pytest.fixture
    def valid_request_body(self) -> dict[str, Any]:
        return {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @patch("llm_gateway.api.bedrock_router.get_settings")
    @patch("llm_gateway.api.bedrock.litellm.token_counter")
    def test_uses_litellm_token_counter(
        self,
        mock_token_counter: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_get_settings.return_value = mock_settings
        mock_token_counter.return_value = 42

        response = authenticated_client.post(
            "/bedrock/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        assert response.json()["input_tokens"] == 42
        call_kwargs = mock_token_counter.call_args.kwargs
        assert call_kwargs["model"] == "bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert call_kwargs["messages"] == valid_request_body["messages"]
        assert call_kwargs["aws_region_name"] == "us-east-1"
