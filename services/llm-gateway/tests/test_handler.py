import asyncio
from collections.abc import AsyncGenerator, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

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
from llm_gateway.callbacks.prometheus import PrometheusCallback
from llm_gateway.callbacks.rate_limiting import RateLimitCallback
from llm_gateway.dependencies import get_authenticated_user
from llm_gateway.main import RequestLoggingMiddleware
from llm_gateway.metrics.prometheus import COST_USD
from llm_gateway.products.config import SIGNALS_DEV_APP_ID
from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import effort_var, get_auth_user, get_effort, throttle_context_var
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
