from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestChatCompletionsEndpoint:
    @pytest.fixture
    def valid_request_body(self) -> dict[str, Any]:
        return {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture
    def mock_openai_response(self) -> dict[str, Any]:
        return {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def test_unauthenticated_request_returns_401(self, client: TestClient, valid_request_body: dict) -> None:
        response = client.post("/v1/chat/completions", json=valid_request_body)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "invalid_body,expected_field",
        [
            pytest.param({}, "model", id="missing_model"),
            pytest.param({"model": "gpt-4"}, "messages", id="missing_messages"),
        ],
    )
    def test_validation_errors(
        self,
        authenticated_client: TestClient,
        invalid_body: dict,
        expected_field: str,
    ) -> None:
        response = authenticated_client.post(
            "/v1/chat/completions",
            json=invalid_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )
        assert response.status_code == 422
        assert expected_field in str(response.json())

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_successful_request(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_openai_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_openai_response)
        mock_completion.return_value = mock_response

        response = authenticated_client.post(
            "/v1/chat/completions",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "chatcmpl-123"
        assert data["object"] == "chat.completion"
        assert data["usage"]["total_tokens"] == 15

    @pytest.mark.parametrize(
        "error_status,error_message,error_type",
        [
            pytest.param(400, "Invalid request", "invalid_request_error", id="bad_request"),
            pytest.param(429, "Rate limit exceeded", "rate_limit_error", id="rate_limited"),
            pytest.param(500, "Internal error", "internal_error", id="server_error"),
            pytest.param(503, "Service unavailable", "service_unavailable", id="service_unavailable"),
        ],
    )
    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_provider_errors(
        self,
        mock_completion: MagicMock,
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
        mock_completion.side_effect = error

        response = authenticated_client.post(
            "/v1/chat/completions",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == error_status
        assert "error" in response.json()["detail"]
