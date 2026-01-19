from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestAnthropicMessagesEndpoint:
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

    def test_unauthenticated_request_returns_401(self, client: TestClient, valid_request_body: dict) -> None:
        response = client.post("/v1/messages", json=valid_request_body)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "invalid_body,expected_field",
        [
            pytest.param({}, "model", id="missing_model"),
            pytest.param({"model": "claude-3"}, "messages", id="missing_messages"),
        ],
    )
    def test_validation_errors(
        self,
        authenticated_client: TestClient,
        invalid_body: dict,
        expected_field: str,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages",
            json=invalid_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )
        assert response.status_code == 422
        assert expected_field in str(response.json())

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_successful_request(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_anthropic_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_anthropic_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "msg_123"
        assert data["role"] == "assistant"
        assert data["usage"]["input_tokens"] == 10

    @pytest.mark.parametrize(
        "error_status,error_message,error_type",
        [
            pytest.param(400, "Invalid request", "invalid_request_error", id="bad_request"),
            pytest.param(429, "Rate limit exceeded", "rate_limit_error", id="rate_limited"),
            pytest.param(500, "Internal error", "internal_error", id="server_error"),
        ],
    )
    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_provider_errors(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        error_status: int,
        error_message: str,
        error_type: str,
    ) -> None:
        error = Exception(error_message)
        error.status_code = error_status  # type: ignore[attr-defined]
        error.message = error_message  # type: ignore[attr-defined]
        error.type = error_type  # type: ignore[attr-defined]
        mock_anthropic.side_effect = error

        response = authenticated_client.post(
            "/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == error_status
        assert "error" in response.json()["detail"]

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_product_prefix_route(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_anthropic_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_anthropic_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/wizard/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "msg_123"

    @pytest.mark.parametrize(
        "product",
        [
            pytest.param("llm_gateway", id="llm_gateway_product"),
            pytest.param("wizard", id="wizard_product"),
        ],
    )
    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_allowed_product_prefixes(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_anthropic_response: dict,
        product: str,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_anthropic_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            f"/{product}/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "product",
        [
            pytest.param("invalid", id="invalid_product"),
            pytest.param("max", id="max_product"),
            pytest.param("claude-code", id="claude_code_product"),
        ],
    )
    def test_invalid_product_returns_400(
        self,
        authenticated_client: TestClient,
        valid_request_body: dict,
        product: str,
    ) -> None:
        response = authenticated_client.post(
            f"/{product}/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert "Invalid product" in response.json()["detail"]
