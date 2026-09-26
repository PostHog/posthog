from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from litellm.exceptions import APIConnectionError

from llm_gateway.api.handler import (
    ANTHROPIC_CONFIG,
    BEDROCK_CONFIG,
    CLOUDFLARE_ANTHROPIC_CONFIG,
    CLOUDFLARE_OPENAI_CONFIG,
    CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
    MODAL_OPENAI_CONFIG,
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
from llm_gateway.request_context import effort_var, get_effort


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


class TestMessageShapeRejection:
    """litellm validates OpenAI message shape before it calls a provider and raises an error with
    no status code, which the handler used to report as a gateway 500 and an error-tracking issue.
    """

    @pytest.mark.parametrize("is_streaming", [False, True])
    @pytest.mark.asyncio
    async def test_invalid_message_shape_is_an_unreported_400(
        self, authenticated_user: AuthenticatedUser, is_streaming: bool
    ) -> None:
        error = APIConnectionError(
            message="Invalid user message at index 0. Please ensure all user messages are valid "
            "OpenAI chat completion messages.",
            llm_provider="openai",
            model="moonshotai/kimi-k3",
        )

        async def failing_call(**kwargs: Any) -> dict[str, Any]:
            raise error

        with patch("llm_gateway.api.handler.capture_exception") as mock_capture:
            with pytest.raises(HTTPException) as exc_info:
                await handle_llm_request(
                    request_data={"messages": [{"role": "user", "content": [{"type": "image"}]}]},
                    user=authenticated_user,
                    model="test-model",
                    is_streaming=is_streaming,
                    provider_config=MODAL_OPENAI_CONFIG,
                    llm_call=failing_call,
                )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"]["type"] == "invalid_request_error"
        mock_capture.assert_not_called()

    @pytest.mark.parametrize("is_streaming", [False, True])
    @pytest.mark.asyncio
    async def test_statusless_provider_failure_stays_a_reported_500(
        self, authenticated_user: AuthenticatedUser, is_streaming: bool
    ) -> None:
        error = APIConnectionError(
            message="Connection reset by peer", llm_provider="openai", model="moonshotai/kimi-k3"
        )

        async def failing_call(**kwargs: Any) -> dict[str, Any]:
            raise error

        with patch("llm_gateway.api.handler.capture_exception") as mock_capture:
            with pytest.raises(HTTPException) as exc_info:
                await handle_llm_request(
                    request_data={"messages": [{"role": "user", "content": "hi"}]},
                    user=authenticated_user,
                    model="test-model",
                    is_streaming=is_streaming,
                    provider_config=MODAL_OPENAI_CONFIG,
                    llm_call=failing_call,
                )

        assert exc_info.value.status_code == 500
        mock_capture.assert_called_once()
