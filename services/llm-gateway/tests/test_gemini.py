from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestGeminiModels:
    @pytest.fixture
    def valid_gemini_request(self) -> dict[str, Any]:
        return {
            "model": "gemini/gemini-3-pro-preview",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture
    def mock_gemini_response(self) -> dict[str, Any]:
        return {
            "id": "chatcmpl-gemini-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gemini/gemini-3-pro-preview",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello! How can I help you?"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }

    def test_unauthenticated_request_returns_401(self, client: TestClient, valid_gemini_request: dict) -> None:
        response = client.post("/v1/chat/completions", json=valid_gemini_request)
        assert response.status_code == 401

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_successful_gemini_request(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_gemini_request: dict,
        mock_gemini_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_gemini_response)
        mock_completion.return_value = mock_response

        response = authenticated_client.post(
            "/v1/chat/completions",
            json=valid_gemini_request,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "gemini/gemini-3-pro-preview"
        assert "choices" in data
        assert data["usage"]["total_tokens"] == 15

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_gemini_vision_request(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        mock_gemini_response: dict,
    ) -> None:
        vision_request = {
            "model": "gemini/gemini-3-flash-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {"type": "image_url", "image_url": {"url": "https://example.com/test.jpg"}},
                    ],
                }
            ],
        }

        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_gemini_response)
        mock_completion.return_value = mock_response

        response = authenticated_client.post(
            "/v1/chat/completions",
            json=vision_request,
            headers={"Authorization": "Bearer phx_test_key"},
        )
        assert response.status_code == 200

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_gemini_streaming_request(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_gemini_request: dict,
    ) -> None:
        async def mock_stream():
            yield {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
            yield {"choices": [{"delta": {"content": " there"}, "finish_reason": "stop"}]}

        mock_completion.return_value = mock_stream()

        streaming_request = {**valid_gemini_request, "stream": True}
        response = authenticated_client.post(
            "/v1/chat/completions",
            json=streaming_request,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
