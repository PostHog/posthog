from collections.abc import Iterator
from typing import Any

import pytest

from llm_gateway.api.handler import (
    ANTHROPIC_CONFIG,
    BEDROCK_CONFIG,
    CLOUDFLARE_ANTHROPIC_CONFIG,
    CLOUDFLARE_OPENAI_CONFIG,
    CLOUDFLARE_OPENAI_RESPONSES_CONFIG,
    CREDENTIAL_REJECTION_ERROR_TYPE,
    OPENAI_CONFIG,
    OPENAI_RESPONSES_CONFIG,
    OPENAI_TRANSCRIPTION_CONFIG,
    ProviderConfig,
    classify_provider_failure,
    effort_from_output_config,
    effort_from_reasoning,
    effort_from_reasoning_effort,
    handle_llm_request,
    no_effort,
)
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.request_context import effort_var, get_effort


class ProviderException(Exception):
    """Stands in for the litellm exceptions the provider call raises."""

    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.type = "invalid_request_error"


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


class TestProviderFailureClassification:
    @pytest.mark.parametrize(
        "status_code, code, message",
        [
            # The status and code litellm exposes on an OpenAI organization refusal.
            (401, "invalid_organization", "You do not have access to the organization tied to the API key."),
            # litellm maps the same refusal onto a 400 with the provider body in the message.
            (400, None, 'OpenAIException - {"error": {"code": "invalid_organization"}, "status": 401}'),
            (401, None, "Incorrect API key provided: sk-***."),
            (403, "invalid_api_key", "Invalid API key"),
        ],
    )
    def test_credential_rejection_replaces_the_upstream_message(
        self, status_code: int, code: str | None, message: str
    ) -> None:
        error = ProviderException(status_code=status_code, code=code, message=message)

        error_type, provider_error = classify_provider_failure(error, "openai")

        assert error_type == CREDENTIAL_REJECTION_ERROR_TYPE
        assert provider_error.status_code == status_code
        detail = provider_error.detail["error"]
        assert detail["type"] == CREDENTIAL_REJECTION_ERROR_TYPE
        assert "PostHog's openai credentials were rejected" in detail["message"]
        assert "not a usage limit" in detail["message"]
        # The upstream wording must not reach the caller: it reads like their own account problem.
        assert message not in detail["message"]

    @pytest.mark.parametrize(
        "status_code, code, message",
        [
            # A caller-side 401 keeps its own message, so an expired token still says so.
            (401, "authentication_error", "Your token has expired"),
            # The signatures only apply to auth-shaped statuses.
            (500, "invalid_organization", "Internal server error"),
            (400, None, "Model 'invalid_organization' is not supported"),
        ],
    )
    def test_other_failures_pass_the_upstream_message_through(
        self, status_code: int, code: str | None, message: str
    ) -> None:
        error = ProviderException(status_code=status_code, code=code, message=message)

        error_type, provider_error = classify_provider_failure(error, "openai")

        assert error_type == "ProviderException"
        assert provider_error.detail["error"]["message"] == message
