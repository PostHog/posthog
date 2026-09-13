from collections.abc import Iterator
from typing import Any

import pytest

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


class TestCallerMetadataInstrumentation:
    @pytest.mark.asyncio
    async def test_caller_metadata_snapshot_preserves_analytics_keys_and_sanitizes_provider_payload(
        self,
        authenticated_user: AuthenticatedUser,
    ) -> None:
        from llm_gateway.callbacks.posthog import PostHogCallback
        from llm_gateway.request_context import get_caller_metadata

        request_data = {
            "metadata": {
                "organization": "my_org",
                "api_version": "2024-01-01",
                "base_url": "https://api.example.com",
                "custom_experiment": "exp_42",
            },
            "organization": "forbidden_top_level",
            "messages": [{"role": "user", "content": "hello"}],
        }

        captured_call_args: dict[str, Any] = {}

        async def mock_llm_call(**kwargs: Any) -> dict[str, Any]:
            captured_call_args["forwarded_request_data"] = kwargs.get("request_data")
            captured_call_args["context_caller_metadata"] = get_caller_metadata()
            return {"ok": True}

        await handle_llm_request(
            request_data=request_data,
            user=authenticated_user,
            model="test-model",
            is_streaming=False,
            provider_config=OPENAI_CONFIG,
            llm_call=mock_llm_call,
        )

        # 1. Verify context snapshot preserves valid analytics keys despite forbidden params
        context_metadata = captured_call_args["context_caller_metadata"]
        assert context_metadata is not None
        assert context_metadata["organization"] == "my_org"
        assert context_metadata["api_version"] == "2024-01-01"
        assert context_metadata["base_url"] == "https://api.example.com"
        assert context_metadata["custom_experiment"] == "exp_42"

        # 2. Verify provider-forwarded request data had forbidden routing params stripped
        forwarded = captured_call_args["forwarded_request_data"]
        assert "organization" not in forwarded
        assert "api_version" not in forwarded.get("metadata", {})
        assert "base_url" not in forwarded.get("metadata", {})

        # 3. Verify callback extracts the snapshot containing preserved analytics properties
        callback = PostHogCallback(api_key="test-key", host="https://test.posthog.com")
        assert extracted == context_metadata
