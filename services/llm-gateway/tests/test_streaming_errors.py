import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, handle_llm_request
from llm_gateway.auth.models import AuthenticatedUser


class MockProviderError(Exception):
    """Mock exception with status_code attribute."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class TestStreamingErrorHandling:
    @pytest.fixture
    def mock_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=123, team_id=456, auth_method="personal_api_key", scopes=["llm_gateway:read"])

    @pytest.mark.asyncio
    async def test_timeout_non_streaming_raises_504(self, mock_user: AuthenticatedUser) -> None:
        async def slow_llm_call(**kwargs):
            await asyncio.sleep(10)

        with patch("llm_gateway.api.handler.get_settings") as mock_settings:
            mock_settings.return_value.streaming_timeout = 0.01
            mock_settings.return_value.request_timeout = 0.01

            with pytest.raises(HTTPException) as exc_info:
                await handle_llm_request(
                    request_data={"model": "test", "messages": []},
                    user=mock_user,
                    model="test-model",
                    is_streaming=False,
                    provider_config=ANTHROPIC_CONFIG,
                    llm_call=slow_llm_call,
                )

            assert exc_info.value.status_code == 504

    @pytest.mark.asyncio
    async def test_provider_error_non_streaming(self, mock_user: AuthenticatedUser) -> None:
        async def failing_llm_call(**kwargs: Any) -> None:
            raise MockProviderError("Service temporarily unavailable", status_code=503)

        with pytest.raises(HTTPException) as exc_info:
            await handle_llm_request(
                request_data={"model": "test", "messages": []},
                user=mock_user,
                model="test-model",
                is_streaming=False,
                provider_config=ANTHROPIC_CONFIG,
                llm_call=failing_llm_call,
            )

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_streaming_response_returns_streaming_response_type(self, mock_user: AuthenticatedUser) -> None:
        async def mock_stream():
            yield {"type": "content_block_delta", "delta": {"text": "Hello"}}
            yield {"type": "message_stop"}

        async def mock_llm_call(**kwargs):
            return mock_stream()

        response = await handle_llm_request(
            request_data={"model": "test", "messages": [], "stream": True},
            user=mock_user,
            model="test-model",
            is_streaming=True,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert isinstance(response, StreamingResponse)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_status,error_type",
        [
            pytest.param(400, "BadRequestError", id="bad_request"),
            pytest.param(401, "AuthenticationError", id="auth_error"),
            pytest.param(429, "RateLimitError", id="rate_limit"),
            pytest.param(500, "InternalServerError", id="internal_error"),
            pytest.param(503, "ServiceUnavailableError", id="service_unavailable"),
        ],
    )
    async def test_error_status_codes_propagate(
        self, mock_user: AuthenticatedUser, error_status: int, error_type: str
    ) -> None:
        async def failing_llm_call(**kwargs: Any) -> None:
            raise MockProviderError(f"{error_type} occurred", status_code=error_status)

        with pytest.raises(HTTPException) as exc_info:
            await handle_llm_request(
                request_data={"model": "test", "messages": []},
                user=mock_user,
                model="test-model",
                is_streaming=False,
                provider_config=ANTHROPIC_CONFIG,
                llm_call=failing_llm_call,
            )

        assert exc_info.value.status_code == error_status


class TestStreamingLifecycle:
    @pytest.fixture
    def mock_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=123, team_id=456, auth_method="personal_api_key", scopes=["llm_gateway:read"])

    @pytest.mark.asyncio
    async def test_successful_stream_completes(self, mock_user: AuthenticatedUser) -> None:
        chunks_yielded = []

        async def mock_stream():
            for i in range(3):
                chunk = {"type": "content_block_delta", "index": i}
                chunks_yielded.append(chunk)
                yield chunk
            chunks_yielded.append({"type": "message_stop"})
            yield {"type": "message_stop"}

        async def mock_llm_call(**kwargs):
            return mock_stream()

        response = await handle_llm_request(
            request_data={"model": "test", "messages": [], "stream": True},
            user=mock_user,
            model="test-model",
            is_streaming=True,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert isinstance(response, StreamingResponse)
        collected = []
        async for chunk in response.body_iterator:
            collected.append(chunk)

        assert len(collected) > 0

    @pytest.mark.asyncio
    async def test_empty_stream_handles_gracefully(self, mock_user: AuthenticatedUser) -> None:
        async def empty_stream():
            return
            yield  # Make it a generator

        async def mock_llm_call(**kwargs):
            return empty_stream()

        response = await handle_llm_request(
            request_data={"model": "test", "messages": [], "stream": True},
            user=mock_user,
            model="test-model",
            is_streaming=True,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert isinstance(response, StreamingResponse)
        collected = []
        async for chunk in response.body_iterator:
            collected.append(chunk)

        # Should at least have the [DONE] marker
        assert any(b"[DONE]" in chunk for chunk in collected)
