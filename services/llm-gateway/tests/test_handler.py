import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest
from anthropic import AsyncAnthropic
from fastapi import Request
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncByteStream, AsyncClient, MockTransport, Response
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from llm_gateway.api.handler import (
    ANTHROPIC_CONFIG,
    BEDROCK_CONFIG,
    CLOUDFLARE_ANTHROPIC_CONFIG,
    CLOUDFLARE_OPENAI_CONFIG,
    CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
    OPENAI_CONFIG,
    OPENAI_RESPONSES_CONFIG,
    OPENAI_TRANSCRIPTION_CONFIG,
    ProviderConfig,
    effort_from_output_config,
    effort_from_reasoning,
    effort_from_reasoning_effort,
    handle_llm_request,
    no_effort,
)
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.callbacks.posthog import PostHogCallback
from llm_gateway.callbacks.private_capture import PrivateScoutLoggingCallback
from llm_gateway.callbacks.prometheus import PrometheusCallback
from llm_gateway.callbacks.rate_limiting import RateLimitCallback
from llm_gateway.dependencies import get_authenticated_user
from llm_gateway.main import RequestLoggingMiddleware
from llm_gateway.metrics.prometheus import COST_USD
from llm_gateway.products.config import SIGNALS_DEV_APP_ID
from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import effort_var, get_auth_user, get_effort, throttle_context_var, throttle_runner_var
from tests.conftest import create_test_app


class TestEffortExtractors:
    @pytest.mark.parametrize(
        "extractor, request_data, expected",
        [
            # Anthropic Messages: output_config.effort
            (effort_from_output_config, {"output_config": {"effort": "medium"}}, "medium"),
            (effort_from_output_config, {"output_config": {"effort": "  medium  "}}, "medium"),
            # Structured-outputs-only request (format, no effort)
            (effort_from_output_config, {"output_config": {"format": {"type": "json_schema"}}}, None),
            (effort_from_output_config, {"output_config": "not-a-dict"}, None),
            (effort_from_output_config, {"output_config": {"effort": 5}}, None),
            (effort_from_output_config, {}, None),
            # OpenAI chat completions: reasoning_effort
            (effort_from_reasoning_effort, {"reasoning_effort": "high"}, "high"),
            (effort_from_reasoning_effort, {"reasoning_effort": "   "}, None),
            # Permissive: a newly-introduced level passes through
            (effort_from_reasoning_effort, {"reasoning_effort": "ultra"}, "ultra"),
            (effort_from_reasoning_effort, {}, None),
            # OpenAI Responses: reasoning.effort
            (effort_from_reasoning, {"reasoning": {"effort": "xhigh"}}, "xhigh"),
            (effort_from_reasoning, {"reasoning": "not-a-dict"}, None),
            (effort_from_reasoning, {}, None),
            # Endpoints without an effort param ignore everything
            (no_effort, {"reasoning_effort": "high"}, None),
        ],
    )
    def test_extractor(self, extractor: Any, request_data: dict[str, Any], expected: str | None) -> None:
        assert extractor(request_data) == expected


class TestEffortInstrumentation:
    @pytest.fixture(autouse=True)
    def reset_effort(self) -> Iterator[None]:
        token = effort_var.set(None)
        yield
        effort_var.reset(token)

    # One case per real config with its surface's natural request shape, so miswiring any
    # config to the wrong extractor (silently dropping $ai_effort for that surface) fails here.
    @pytest.mark.parametrize(
        "provider_config, request_data, expected",
        [
            (ANTHROPIC_CONFIG, {"output_config": {"effort": "medium"}}, "medium"),
            (BEDROCK_CONFIG, {"output_config": {"effort": "low"}}, "low"),
            (OPENAI_CONFIG, {"reasoning_effort": "high"}, "high"),
            (OPENAI_RESPONSES_CONFIG, {"reasoning": {"effort": "xhigh"}}, "xhigh"),
            (OPENAI_TRANSCRIPTION_CONFIG, {"reasoning_effort": "high"}, None),
            (CLOUDFLARE_ANTHROPIC_CONFIG, {"output_config": {"effort": "medium"}}, "medium"),
            (CLOUDFLARE_OPENAI_CONFIG, {"reasoning_effort": "high"}, "high"),
            (CLOUDFLARE_OPENAI_RESPONSES_CONFIG, {"reasoning": {"effort": "xhigh"}}, "xhigh"),
            # No effort in the request resets any stale context value to None
            (ANTHROPIC_CONFIG, {}, None),
        ],
    )
    @pytest.mark.asyncio
    async def test_effort_from_request_reaches_context(
        self,
        authenticated_user: AuthenticatedUser,
        provider_config: ProviderConfig,
        request_data: dict[str, Any],
        expected: str | None,
    ) -> None:
        # Pre-seed a stale value: handle_llm_request must set effort unconditionally, so the
        # no-effort case resets to None rather than leaking the stale value into the callback.
        effort_var.set("stale")
        captured: dict[str, Any] = {}

        async def mock_llm_call(**kwargs: Any) -> dict[str, Any]:
            captured["effort"] = get_effort()
            return {"ok": True}

        await handle_llm_request(
            request_data=request_data,
            user=authenticated_user,
            model="test-model",
            is_streaming=False,
            provider_config=provider_config,
            llm_call=mock_llm_call,
        )

        assert captured["effort"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_concurrent_private_and_regular_scout_requests_preserve_costs(
    streaming: bool,
    mock_db_pool: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rendezvous = asyncio.Barrier(2)
    capture_callback = PostHogCallback(
        api_key="test-primary",
        host="https://primary.example.com",
        secondary_api_key="test-secondary",
        secondary_host="https://secondary.example.com",
    )
    cost_callback = RateLimitCallback()
    metrics_callback = PrometheusCallback()
    throttle = ProductCostThrottle(redis=None)
    app = create_test_app(mock_db_pool, throttles=[throttle])
    app.add_middleware(RequestLoggingMiddleware)
    contexts: list[ThrottleContext] = []
    metric = COST_USD.labels(provider="openai", model="gpt-4", product="signals")
    cost_before = metric._value.get()

    async def authenticate(request: Request) -> AuthenticatedUser:
        private = request.headers["x-test-scout"] == "private"
        scopes = ["llm_gateway:read", "internal_run:read"]
        if private:
            scopes.append("scout_experiment_internal:read")
        return AuthenticatedUser(
            user_id=1 if private else 2,
            team_id=1,
            auth_method="oauth_access_token",
            distinct_id="private" if private else "regular",
            scopes=scopes,
            application_id=SIGNALS_DEV_APP_ID,
            sandbox_task_id="test-task",
        )

    app.dependency_overrides[get_authenticated_user] = authenticate

    async def provider(**_kwargs: object) -> dict[str, str] | AsyncGenerator[bytes]:
        user = get_auth_user()
        context = throttle_context_var.get()
        assert user is not None
        assert context is not None
        contexts.append(context)
        await rendezvous.wait()
        logging.getLogger("LiteLLM").warning("provider-log-%s", user.distinct_id)

        async def complete() -> None:
            logging_data = {
                "standard_logging_object": {
                    "model": "gpt-4",
                    "custom_llm_provider": "openai",
                    "messages": [{"role": "user", "content": user.distinct_id}],
                    "response": user.distinct_id,
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "response_cost": 0.05,
                }
            }
            for callback in (capture_callback, cost_callback, metrics_callback):
                await callback.async_log_success_event(logging_data, None, 0.0, 1.0)

        async def chunks() -> AsyncGenerator[bytes]:
            yield b"data: hello\n\n"
            await complete()

        if streaming:
            return chunks()
        await complete()
        return {"content": "hello"}

    with (
        patch("llm_gateway.callbacks.posthog.Posthog") as capture_client,
        patch("llm_gateway.callbacks.posthog.asyncio") as capture_asyncio,
        patch("llm_gateway.api.openai.litellm.acompletion", side_effect=provider),
        patch("llm_gateway.rate_limiting.cost_refresh.get_model_cost_map", return_value=litellm.model_cost),
    ):
        capture_asyncio.get_running_loop.return_value.run_in_executor.side_effect = lambda _executor, call: call()
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            responses = await asyncio.wait_for(
                asyncio.gather(
                    *[
                        client.post(
                            "/signals/v1/chat/completions",
                            json={
                                "model": "gpt-4",
                                "stream": streaming,
                                "messages": [{"role": "user", "content": scout}],
                            },
                            headers={"x-test-scout": scout},
                        )
                        for scout in ("private", "regular")
                    ]
                ),
                timeout=5,
            )

    for response in responses:
        assert response.status_code == 200
        if streaming:
            assert response.text == "data: hello\n\n"
        else:
            assert response.json() == {"content": "hello"}

    captures = capture_client.return_value.capture.call_args_list
    assert len(captures) == 2
    assert {call.kwargs["distinct_id"] for call in captures} == {"regular"}
    assert metric._value.get() == pytest.approx(cost_before + 0.1)
    status = await throttle.get_status(contexts[0])
    assert status.used_usd == pytest.approx(0.1)
    assert "provider-log-private" not in caplog.text
    assert "provider-log-regular" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "anthropic"])
async def test_real_responses_streams_preserve_private_capture_and_costs(
    api: str, caplog: pytest.LogCaptureFixture
) -> None:
    rendezvous = asyncio.Barrier(2)
    throttle = ProductCostThrottle(redis=None)
    runner = ThrottleRunner([throttle])
    contexts: list[ThrottleContext] = []
    finished = {scout: threading.Event() for scout in ("private", "regular")}
    captured = threading.Event()
    capture_callback = PostHogCallback(api_key="synthetic-key", host="https://capture.example.com")
    metric = COST_USD.labels(provider="openai", model="gpt-4o-mini", product="signals")
    cost_before = metric._value.get()
    original_success = Logging.async_success_handler

    async def success(logging_obj: Logging, *args: Any, **kwargs: Any) -> Any:
        user = get_auth_user()
        assert user is not None
        try:
            return await original_success(logging_obj, *args, **kwargs)
        finally:
            finished[user.distinct_id].set()

    class ProviderStream(AsyncByteStream):
        async def __aiter__(self) -> AsyncGenerator[bytes]:
            await rendezvous.wait()
            user = get_auth_user()
            assert user is not None
            logging.getLogger("LiteLLM").warning("synthetic-stream-%s", user.distinct_id)
            response = {
                "id": "resp_synthetic",
                "created_at": 1,
                "model": "gpt-4o-mini",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_synthetic",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "synthetic reply", "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            }
            events = [
                {
                    "type": "response.created",
                    "response": {**response, "status": "in_progress", "output": [], "usage": None},
                },
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_synthetic",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "synthetic reply",
                },
                {"type": "response.completed", "response": response},
            ]
            for event in events:
                yield f"data: {json.dumps(event)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    async with AsyncClient(
        transport=MockTransport(
            lambda _request: Response(200, headers={"content-type": "text/event-stream"}, stream=ProviderStream())
        )
    ) as client:
        with patch.object(AsyncHTTPHandler, "create_client", return_value=client):
            provider_client = AsyncHTTPHandler()

        async def provider(**kwargs: Any) -> Any:
            call = litellm.aresponses if api == "responses" else litellm.anthropic_messages
            return await call(client=provider_client, api_key="synthetic-key", **kwargs)

        async def run(scout: str) -> None:
            scopes = ["llm_gateway:read", "internal_run:read"]
            if scout == "private":
                scopes.append("scout_experiment_internal:read")
            user = AuthenticatedUser(
                user_id=1 if scout == "private" else 2,
                team_id=1,
                auth_method="oauth_access_token",
                distinct_id=scout,
                scopes=scopes,
                application_id=SIGNALS_DEV_APP_ID,
                sandbox_task_id="synthetic-task",
            )
            context = ThrottleContext(user=user, product="signals")
            contexts.append(context)
            runner_token = throttle_runner_var.set(runner)
            context_token = throttle_context_var.set(context)
            try:
                response = await handle_llm_request(
                    request_data={
                        "model": "gpt-4o-mini",
                        "stream": True,
                        "max_tokens": 50,
                        **(
                            {"input": scout}
                            if api == "responses"
                            else {"messages": [{"role": "user", "content": scout}]}
                        ),
                    },
                    user=user,
                    model="gpt-4o-mini",
                    product="signals",
                    is_streaming=True,
                    provider_config=OPENAI_RESPONSES_CONFIG if api == "responses" else ANTHROPIC_CONFIG,
                    llm_call=provider,
                )
                assert isinstance(response, StreamingResponse)
                chunks = [chunk async for chunk in response.body_iterator]
                assert any("synthetic reply" in str(chunk) for chunk in chunks)
                assert await asyncio.to_thread(finished[scout].wait, 5)
                if api == "anthropic":
                    async with AsyncClient(
                        transport=MockTransport(
                            lambda _request: Response(
                                200, headers={"content-type": "text/event-stream"}, content=b"".join(chunks)
                            )
                        )
                    ) as gateway_client:
                        sdk = AsyncAnthropic(api_key="synthetic-key", http_client=gateway_client, max_retries=0)
                        async with sdk.messages.stream(
                            model="gpt-4o-mini",
                            max_tokens=50,
                            messages=[{"role": "user", "content": "synthetic prompt"}],
                        ) as sdk_stream:
                            message = await sdk_stream.get_final_message()
                        assert message.stop_reason == "end_turn"
                        assert message.usage.input_tokens == 10
                        assert message.usage.output_tokens == 20
            finally:
                throttle_runner_var.reset(runner_token)
                throttle_context_var.reset(context_token)

        with (
            patch("socket.socket.connect", side_effect=AssertionError("Unexpected network connection")) as connect,
            patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS lookup")) as resolve,
            patch.object(Logging, "async_success_handler", success),
            patch("litellm.callbacks", [PrivateScoutLoggingCallback()]),
            patch("litellm._async_success_callback", [capture_callback, RateLimitCallback(), PrometheusCallback()]),
            patch("llm_gateway.callbacks.posthog.Posthog") as capture_client,
        ):
            capture_client.return_value.capture.side_effect = lambda **_kwargs: captured.set()
            await asyncio.wait_for(asyncio.gather(run("private"), run("regular")), timeout=10)
            assert await asyncio.to_thread(captured.wait, 5)
            connect.assert_not_called()
            resolve.assert_not_called()

    captures = capture_client.return_value.capture.call_args_list
    assert len(captures) == 1
    assert captures[0].kwargs["distinct_id"] == "regular"
    expected_cost = 2 * (10 * 0.00000015 + 20 * 0.0000006)
    assert metric._value.get() == pytest.approx(cost_before + expected_cost)
    assert (await throttle.get_status(contexts[0])).used_usd == pytest.approx(expected_cost)
    assert "synthetic-stream-private" not in caplog.text
    assert "synthetic-stream-regular" in caplog.text
