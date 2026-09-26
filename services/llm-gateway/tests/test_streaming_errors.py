import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import litellm
import pytest
from anthropic import APIStatusError, AsyncAnthropic
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from litellm.exceptions import MidStreamFallbackError
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from openai import AsyncOpenAI

from llm_gateway.anthropic_stream import IncompleteAnthropicStreamError
from llm_gateway.api.handler import ANTHROPIC_CONFIG, OPENAI_CONFIG, OPENAI_RESPONSES_CONFIG, handle_llm_request
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.callbacks import init_callbacks
from llm_gateway.config import Settings
from llm_gateway.metrics.prometheus import PROVIDER_ERRORS, REQUEST_COUNT
from llm_gateway.products.config import SIGNALS_DEV_APP_ID


class MockProviderError(Exception):
    """Mock exception with status_code attribute."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class TestStreamingErrorHandling:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("api", ["chat", "responses", "anthropic"])
    @pytest.mark.parametrize("private_scout", [False, True])
    async def test_provider_background_stream_errors_keep_capture_policy(
        self,
        mock_user: AuthenticatedUser,
        api: str,
        private_scout: bool,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_user.auth_method = "oauth_access_token"
        mock_user.application_id = SIGNALS_DEV_APP_ID
        mock_user.sandbox_task_id = "test-task"
        mock_user.scopes = ["llm_gateway:read", "internal_run:read"]
        if private_scout:
            mock_user.scopes.append("scout_experiment_internal:read")
        finished = [threading.Event(), threading.Event()]
        sync_failure = Logging.failure_handler
        async_failure = Logging.async_failure_handler

        def failure(logging_obj: Logging, *args: Any, **kwargs: Any) -> Any:
            try:
                return sync_failure(logging_obj, *args, **kwargs)
            finally:
                finished[0].set()

        async def afailure(logging_obj: Logging, *args: Any, **kwargs: Any) -> Any:
            try:
                return await async_failure(logging_obj, *args, **kwargs)
            finally:
                finished[1].set()

        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncGenerator[bytes]:
                chunk = (
                    {
                        "id": "synthetic-stream",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "gpt-4o-mini",
                        "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
                    }
                    if api == "chat"
                    else {
                        "type": "response.created",
                        "response": {"id": "resp_synthetic", "created_at": 1, "model": "gpt-4o-mini", "output": []},
                    }
                )
                yield f"data: {json.dumps(chunk)}\n\n".encode()
                if api == "anthropic":
                    delta = {
                        "type": "response.output_text.delta",
                        "item_id": "msg_synthetic",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": "synthetic partial reply",
                    }
                    yield f"data: {json.dumps(delta)}\n\n".encode()
                raise httpx.ReadError("synthetic-provider-stream-error")

        def transport(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=BrokenStream())

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with patch.object(AsyncHTTPHandler, "create_client", return_value=client):
                responses_client = AsyncHTTPHandler()
            chat_client = AsyncOpenAI(api_key="synthetic-key", http_client=client)

            async def provider(**kwargs: Any) -> Any:
                if api == "chat":
                    return await litellm.acompletion(client=chat_client, **kwargs)
                call = litellm.aresponses if api == "responses" else litellm.anthropic_messages
                return await call(client=responses_client, api_key="synthetic-key", **kwargs)

            with (
                patch("socket.socket.connect", side_effect=AssertionError("Unexpected network connection")) as connect,
                patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS lookup")) as resolve,
                patch.object(Logging, "failure_handler", failure),
                patch.object(Logging, "async_failure_handler", afailure),
                patch.multiple(
                    litellm,
                    callbacks=[],
                    input_callback=[],
                    success_callback=[],
                    failure_callback=[],
                    _async_success_callback=[],
                    _async_failure_callback=[],
                ),
                patch("llm_gateway.callbacks.get_settings", return_value=Settings(posthog_project_token="")),
                patch(
                    "litellm.litellm_core_utils.litellm_logging._get_response_headers",
                    side_effect=ValueError("synthetic-provider-bookkeeping-detail"),
                ),
                patch("llm_gateway.observability.error_tracking.posthoganalytics"),
            ):
                init_callbacks()
                caplog.clear()
                response = await handle_llm_request(
                    request_data={
                        "model": "gpt-4o-mini",
                        "stream": True,
                        "max_tokens": 50,
                        **(
                            {"messages": [{"role": "user", "content": "synthetic prompt"}]}
                            if api != "responses"
                            else {"input": "synthetic prompt"}
                        ),
                    },
                    user=mock_user,
                    model="gpt-4o-mini",
                    product="signals",
                    is_streaming=True,
                    provider_config={
                        "chat": OPENAI_CONFIG,
                        "responses": OPENAI_RESPONSES_CONFIG,
                        "anthropic": ANTHROPIC_CONFIG,
                    }[api],
                    llm_call=provider,
                )
                assert isinstance(response, StreamingResponse)
                expected_error = (
                    RuntimeError
                    if private_scout
                    else {
                        "chat": MidStreamFallbackError,
                        "responses": httpx.ReadError,
                        "anthropic": IncompleteAnthropicStreamError,
                    }[api]
                )
                chunks: list[bytes] = []
                with pytest.raises(expected_error):
                    async for chunk in response.body_iterator:
                        assert isinstance(chunk, bytes)
                        chunks.append(chunk)
                assert all(await asyncio.gather(*(asyncio.to_thread(event.wait, 5) for event in finished)))
                if api == "anthropic":
                    async with httpx.AsyncClient(
                        transport=httpx.MockTransport(
                            lambda _request: httpx.Response(
                                200, headers={"content-type": "text/event-stream"}, content=b"".join(chunks)
                            )
                        )
                    ) as gateway_client:
                        sdk = AsyncAnthropic(api_key="synthetic-key", http_client=gateway_client, max_retries=0)
                        with pytest.raises(APIStatusError, match="Upstream stream failed") as sdk_error:
                            async with sdk.messages.stream(
                                model="gpt-4o-mini",
                                max_tokens=50,
                                messages=[{"role": "user", "content": "synthetic prompt"}],
                            ) as sdk_stream:
                                await sdk_stream.get_final_message()
                        assert sdk_error.value.body == {
                            "type": "error",
                            "error": {"type": "api_error", "message": "Upstream stream failed"},
                        }
                connect.assert_not_called()
                resolve.assert_not_called()

        assert ("synthetic-provider-bookkeeping-detail" in caplog.text) is not private_scout

    @pytest.mark.asyncio
    @pytest.mark.parametrize("private_scout", [False, True])
    @pytest.mark.parametrize("failure_at", ["nonstreaming", "stream_start", "stream_chunk"])
    async def test_private_provider_errors_do_not_reach_capture_or_logs(
        self,
        mock_user: AuthenticatedUser,
        private_scout: bool,
        failure_at: str,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_user.auth_method = "oauth_access_token"
        mock_user.application_id = SIGNALS_DEV_APP_ID
        mock_user.sandbox_task_id = "test-task"
        mock_user.scopes = ["llm_gateway:read", "internal_run:read"]
        if private_scout:
            mock_user.scopes.append("scout_experiment_internal:read")

        async def failing_stream() -> AsyncGenerator[bytes]:
            yield b"data: started\n\n"
            logging.getLogger("LiteLLM").warning("synthetic-private-provider-log")
            raise MockProviderError("synthetic-private-error-detail", 503)

        async def provider(**_kwargs: object) -> AsyncGenerator[bytes]:
            if failure_at == "stream_chunk":
                return failing_stream()
            logging.getLogger("LiteLLM").warning("synthetic-private-provider-log")
            raise MockProviderError("synthetic-private-error-detail", 503)

        with (
            patch("llm_gateway.observability.error_tracking.posthoganalytics") as capture,
            patch(
                "llm_gateway.observability.error_tracking.get_settings",
                return_value=MagicMock(posthog_project_token="test-token"),
            ),
        ):
            capsys.readouterr()
            caplog.clear()
            if failure_at == "stream_chunk":
                response = await handle_llm_request(
                    request_data={},
                    user=mock_user,
                    model="test-model",
                    product="signals",
                    is_streaming=True,
                    provider_config=ANTHROPIC_CONFIG,
                    llm_call=provider,
                )
                assert isinstance(response, StreamingResponse)
                with pytest.raises(RuntimeError if private_scout else MockProviderError) as stream_error:
                    async for _ in response.body_iterator:
                        pass
                if private_scout:
                    assert str(stream_error.value) == "Upstream stream failed"
                    assert stream_error.value.__suppress_context__
            else:
                with pytest.raises(HTTPException) as error:
                    await handle_llm_request(
                        request_data={},
                        user=mock_user,
                        model="test-model",
                        product="signals",
                        is_streaming=failure_at == "stream_start",
                        provider_config=ANTHROPIC_CONFIG,
                        llm_call=provider,
                    )
                assert error.value.status_code == 503

        assert capture.capture_exception.call_count == (0 if private_scout else 1)
        logs = capsys.readouterr().out
        if private_scout:
            assert logs == ""
            assert "synthetic-private-provider-log" not in caplog.text
        else:
            assert "synthetic-private-error-detail" in logs
            assert "synthetic-private-provider-log" in caplog.text

    @pytest.fixture
    def mock_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="personal_api_key",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
        )

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


class TestPreStreamErrors:
    @pytest.fixture
    def mock_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="personal_api_key",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
        )

    @pytest.mark.asyncio
    async def test_streaming_timeout_before_first_chunk_raises_504(self, mock_user: AuthenticatedUser) -> None:
        async def slow_llm_call(**kwargs: Any) -> None:
            await asyncio.sleep(10)

        with patch("llm_gateway.api.handler.get_settings") as mock_settings:
            mock_settings.return_value.streaming_timeout = 0.01
            mock_settings.return_value.request_timeout = 0.01

            with pytest.raises(HTTPException) as exc_info:
                await handle_llm_request(
                    request_data={"model": "test", "messages": [], "stream": True},
                    user=mock_user,
                    model="test-model",
                    is_streaming=True,
                    provider_config=ANTHROPIC_CONFIG,
                    llm_call=slow_llm_call,
                )

            assert exc_info.value.status_code == 504

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_status,error_message,error_type",
        [
            pytest.param(400, "Invalid request", "invalid_request_error", id="bad_request"),
            pytest.param(503, "Service unavailable", "service_unavailable", id="unavailable"),
            pytest.param(529, "Overloaded", "overloaded_error", id="overloaded"),
        ],
    )
    async def test_streaming_provider_error_before_first_chunk_raises_with_status(
        self, mock_user: AuthenticatedUser, error_status: int, error_message: str, error_type: str
    ) -> None:
        async def failing_llm_call(**kwargs: Any) -> None:
            error = MockProviderError(error_message, status_code=error_status)
            error.type = error_type  # type: ignore[attr-defined]
            raise error

        with pytest.raises(HTTPException) as exc_info:
            await handle_llm_request(
                request_data={"model": "test", "messages": [], "stream": True},
                user=mock_user,
                model="test-model",
                is_streaming=True,
                provider_config=ANTHROPIC_CONFIG,
                llm_call=failing_llm_call,
            )

        assert exc_info.value.status_code == error_status
        assert exc_info.value.detail["error"]["message"] == error_message
        assert exc_info.value.detail["error"]["type"] == error_type


class TestStreamingLifecycle:
    @pytest.fixture
    def mock_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="personal_api_key",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
        )

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


def _get_request_count(status_code: str, model: str = "test-model") -> float:
    return REQUEST_COUNT.labels(
        endpoint="anthropic_messages",
        provider="anthropic",
        model=model,
        status_code=status_code,
        auth_method="personal_api_key",
        product="llm_gateway",
    )._value.get()


class TestRequestCountMetrics:
    @pytest.fixture
    def mock_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="personal_api_key",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_status",
        [
            pytest.param(400, id="bad_request"),
            pytest.param(401, id="auth_error"),
            pytest.param(429, id="rate_limit"),
            pytest.param(500, id="internal_error"),
            pytest.param(503, id="service_unavailable"),
        ],
    )
    async def test_non_streaming_error_records_request_count(
        self, mock_user: AuthenticatedUser, error_status: int
    ) -> None:
        before = _get_request_count(str(error_status))

        async def failing_llm_call(**kwargs: Any) -> None:
            raise MockProviderError("error", status_code=error_status)

        with pytest.raises(HTTPException):
            await handle_llm_request(
                request_data={"model": "test", "messages": []},
                user=mock_user,
                model="test-model",
                is_streaming=False,
                provider_config=ANTHROPIC_CONFIG,
                llm_call=failing_llm_call,
            )

        assert _get_request_count(str(error_status)) == before + 1

    @pytest.mark.asyncio
    async def test_non_streaming_timeout_records_request_count_504(self, mock_user: AuthenticatedUser) -> None:
        before = _get_request_count("504")

        async def slow_llm_call(**kwargs: Any) -> None:
            await asyncio.sleep(10)

        with patch("llm_gateway.api.handler.get_settings") as mock_settings:
            mock_settings.return_value.streaming_timeout = 0.01
            mock_settings.return_value.request_timeout = 0.01

            with pytest.raises(HTTPException):
                await handle_llm_request(
                    request_data={"model": "test", "messages": []},
                    user=mock_user,
                    model="test-model",
                    is_streaming=False,
                    provider_config=ANTHROPIC_CONFIG,
                    llm_call=slow_llm_call,
                )

        assert _get_request_count("504") == before + 1

    @pytest.mark.asyncio
    async def test_streaming_mid_stream_error_records_request_count(self, mock_user: AuthenticatedUser) -> None:
        before = _get_request_count("500")

        async def error_stream() -> AsyncGenerator[dict[str, Any]]:
            yield {"type": "content_block_delta", "delta": {"text": "Hello"}}
            raise ValueError("mid-stream failure")

        async def mock_llm_call(**kwargs: Any) -> AsyncGenerator[dict[str, Any]]:
            return error_stream()

        response = await handle_llm_request(
            request_data={"model": "test", "messages": [], "stream": True},
            user=mock_user,
            model="test-model",
            is_streaming=True,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert isinstance(response, StreamingResponse)
        try:
            async for _ in response.body_iterator:
                pass
        except Exception:
            pass

        assert _get_request_count("500") == before + 1

    @pytest.mark.asyncio
    async def test_streaming_mid_stream_error_records_provider_errors(self, mock_user: AuthenticatedUser) -> None:
        before = PROVIDER_ERRORS.labels(
            provider="anthropic", error_type="ValueError", product="llm_gateway"
        )._value.get()

        async def error_stream() -> AsyncGenerator[dict[str, Any]]:
            yield {"type": "content_block_delta", "delta": {"text": "Hello"}}
            raise ValueError("mid-stream failure")

        async def mock_llm_call(**kwargs: Any) -> AsyncGenerator[dict[str, Any]]:
            return error_stream()

        response = await handle_llm_request(
            request_data={"model": "test", "messages": [], "stream": True},
            user=mock_user,
            model="test-model",
            is_streaming=True,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert isinstance(response, StreamingResponse)
        try:
            async for _ in response.body_iterator:
                pass
        except Exception:
            pass

        after = PROVIDER_ERRORS.labels(
            provider="anthropic", error_type="ValueError", product="llm_gateway"
        )._value.get()
        assert after == before + 1
