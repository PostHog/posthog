from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from llm_gateway.api.handler import ANTHROPIC_CONFIG, OPENAI_CONFIG, handle_llm_request
from llm_gateway.auth.models import AuthenticatedUser


@pytest.fixture
def authenticated_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=123,
        team_id=456,
        auth_method="personal_api_key",
        scopes=["llm_gateway:read"],
    )


@pytest.fixture
def anthropic_response() -> MagicMock:
    return MagicMock(
        model_dump=MagicMock(
            return_value={
                "model": "claude-3-opus-20240229",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello! How can I help you?"}],
                "usage": {"input_tokens": 15, "output_tokens": 8},
            }
        )
    )


@pytest.fixture
def openai_response() -> MagicMock:
    return MagicMock(
        model_dump=MagicMock(
            return_value={
                "model": "gpt-4",
                "choices": [{"message": {"role": "assistant", "content": "Hi there!"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }
        )
    )


@pytest.fixture
def mock_analytics_service():
    with patch("llm_gateway.api.handler.get_analytics_service") as mock_get:
        mock_service = MagicMock()
        mock_get.return_value = mock_service
        yield mock_service


class TestAnalyticsCapture:
    @pytest.mark.asyncio
    async def test_captures_anthropic_generation_event(
        self,
        authenticated_user: AuthenticatedUser,
        anthropic_response: MagicMock,
        mock_analytics_service: MagicMock,
    ) -> None:
        mock_llm = AsyncMock(return_value=anthropic_response)
        input_messages = [{"role": "user", "content": "Hello"}]

        await handle_llm_request(
            request_data={"model": "claude-3-opus", "messages": input_messages},
            user=authenticated_user,
            model="claude-3-opus",
            is_streaming=False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm,
        )

        mock_analytics_service.capture.assert_called_once()
        call_kwargs = mock_analytics_service.capture.call_args.kwargs

        assert call_kwargs["user"] == authenticated_user
        assert call_kwargs["model"] == "claude-3-opus"
        assert call_kwargs["provider"] == "anthropic"
        assert call_kwargs["input_messages"] == input_messages
        assert call_kwargs["is_streaming"] is False
        assert call_kwargs["input_tokens_field"] == "input_tokens"
        assert call_kwargs["output_tokens_field"] == "output_tokens"
        assert call_kwargs["latency_seconds"] > 0
        assert call_kwargs["response"]["model"] == "claude-3-opus-20240229"
        assert call_kwargs["response"]["usage"]["input_tokens"] == 15
        assert call_kwargs["error"] is None

    @pytest.mark.asyncio
    async def test_captures_openai_generation_event(
        self,
        authenticated_user: AuthenticatedUser,
        openai_response: MagicMock,
        mock_analytics_service: MagicMock,
    ) -> None:
        mock_llm = AsyncMock(return_value=openai_response)
        input_messages = [{"role": "user", "content": "Hi"}]

        await handle_llm_request(
            request_data={"model": "gpt-4", "messages": input_messages},
            user=authenticated_user,
            model="gpt-4",
            is_streaming=False,
            provider_config=OPENAI_CONFIG,
            llm_call=mock_llm,
        )

        mock_analytics_service.capture.assert_called_once()
        call_kwargs = mock_analytics_service.capture.call_args.kwargs

        assert call_kwargs["provider"] == "openai"
        assert call_kwargs["input_tokens_field"] == "prompt_tokens"
        assert call_kwargs["output_tokens_field"] == "completion_tokens"
        assert call_kwargs["response"]["usage"]["prompt_tokens"] == 12

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status_code",
        [
            pytest.param(400, id="bad_request"),
            pytest.param(500, id="server_error"),
        ],
    )
    async def test_captures_error_event(
        self,
        authenticated_user: AuthenticatedUser,
        mock_analytics_service: MagicMock,
        status_code: int,
    ) -> None:
        error = Exception("Something went wrong")
        error.status_code = status_code  # type: ignore
        error.message = "Something went wrong"  # type: ignore
        error.type = "test_error"  # type: ignore
        mock_llm = AsyncMock(side_effect=error)

        with pytest.raises(HTTPException) as exc_info:
            await handle_llm_request(
                request_data={"model": "claude-3", "messages": []},
                user=authenticated_user,
                model="claude-3",
                is_streaming=False,
                provider_config=ANTHROPIC_CONFIG,
                llm_call=mock_llm,
            )

        assert exc_info.value.status_code == status_code

        mock_analytics_service.capture.assert_called_once()
        call_kwargs = mock_analytics_service.capture.call_args.kwargs
        assert call_kwargs["error"] is error
        assert call_kwargs["response"] is None

    @pytest.mark.asyncio
    async def test_captures_streaming_event_after_stream_consumed(
        self,
        authenticated_user: AuthenticatedUser,
        mock_analytics_service: MagicMock,
    ) -> None:
        async def mock_stream():
            yield MagicMock(model_dump=MagicMock(return_value={"content": "chunk1"}))
            yield MagicMock(model_dump=MagicMock(return_value={"content": "chunk2"}))

        mock_llm = AsyncMock(return_value=mock_stream())

        response = await handle_llm_request(
            request_data={"model": "claude-3", "messages": [{"role": "user", "content": "Hi"}]},
            user=authenticated_user,
            model="claude-3",
            is_streaming=True,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm,
        )

        # Must consume stream to trigger finally block
        async for _ in response.body_iterator:
            pass

        mock_analytics_service.capture.assert_called_once()
        call_kwargs = mock_analytics_service.capture.call_args.kwargs
        assert call_kwargs["is_streaming"] is True

    @pytest.mark.asyncio
    async def test_no_capture_when_analytics_disabled(
        self,
        authenticated_user: AuthenticatedUser,
        anthropic_response: MagicMock,
    ) -> None:
        with patch("llm_gateway.api.handler.get_analytics_service", return_value=None):
            mock_llm = AsyncMock(return_value=anthropic_response)

            result = await handle_llm_request(
                request_data={"model": "claude-3", "messages": []},
                user=authenticated_user,
                model="claude-3",
                is_streaming=False,
                provider_config=ANTHROPIC_CONFIG,
                llm_call=mock_llm,
            )

            # Request should succeed even without analytics
            assert result["model"] == "claude-3-opus-20240229"

    @pytest.mark.asyncio
    async def test_analytics_error_does_not_fail_request(
        self,
        authenticated_user: AuthenticatedUser,
        anthropic_response: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_service = MagicMock()
        mock_service.capture.side_effect = Exception("Analytics failed!")

        with patch("llm_gateway.api.handler.get_analytics_service", return_value=mock_service):
            mock_llm = AsyncMock(return_value=anthropic_response)

            result = await handle_llm_request(
                request_data={"model": "claude-3", "messages": []},
                user=authenticated_user,
                model="claude-3",
                is_streaming=False,
                provider_config=ANTHROPIC_CONFIG,
                llm_call=mock_llm,
            )

            # Request should succeed despite analytics failure
            assert result["model"] == "claude-3-opus-20240229"
