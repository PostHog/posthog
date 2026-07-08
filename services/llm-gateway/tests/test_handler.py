from typing import Any

import pytest

from llm_gateway.api.handler import ANTHROPIC_CONFIG, _extract_effort, handle_llm_request
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.request_context import get_posthog_properties, request_context_var


class TestExtractEffort:
    def test_anthropic_output_config_effort(self) -> None:
        assert _extract_effort({"output_config": {"effort": "medium"}}) == "medium"

    def test_openai_reasoning_effort(self) -> None:
        assert _extract_effort({"reasoning_effort": "high"}) == "high"

    def test_openai_responses_reasoning_effort(self) -> None:
        assert _extract_effort({"reasoning": {"effort": "xhigh"}}) == "xhigh"

    def test_none_when_absent(self) -> None:
        assert _extract_effort({"model": "claude-opus-4-8", "messages": []}) is None

    def test_none_when_output_config_has_no_effort(self) -> None:
        # Structured-outputs-only requests set output_config.format but no effort.
        assert _extract_effort({"output_config": {"format": {"type": "json_schema"}}}) is None

    def test_output_config_wins_over_reasoning_effort(self) -> None:
        # Anthropic native effort takes precedence when multiple shapes are present.
        assert _extract_effort({"output_config": {"effort": "low"}, "reasoning_effort": "high"}) == "low"

    def test_whitespace_is_stripped(self) -> None:
        assert _extract_effort({"reasoning_effort": "  high  "}) == "high"

    def test_non_string_effort_ignored(self) -> None:
        assert _extract_effort({"output_config": {"effort": 5}}) is None

    def test_novel_effort_level_passes_through(self) -> None:
        # Kept permissive so a newly-introduced level isn't silently dropped.
        assert _extract_effort({"reasoning_effort": "ultra"}) == "ultra"

    def test_malformed_output_config_ignored(self) -> None:
        assert _extract_effort({"output_config": "not-a-dict"}) is None


class TestEffortInstrumentation:
    @pytest.fixture
    def mock_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="personal_api_key",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
        )

    @pytest.fixture(autouse=True)
    def reset_context(self):
        token = request_context_var.set(None)
        yield
        request_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_effort_lands_on_request_context(self, mock_user: AuthenticatedUser) -> None:
        captured: dict[str, Any] = {}

        async def mock_llm_call(**kwargs: Any) -> dict[str, Any]:
            # set_posthog_properties runs before the provider call, so the effort
            # is visible on the context the PostHog callback later reads.
            captured["properties"] = get_posthog_properties()
            return {"ok": True}

        await handle_llm_request(
            request_data={"model": "test", "messages": [], "output_config": {"effort": "medium"}},
            user=mock_user,
            model="test-model",
            is_streaming=False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert captured["properties"]["$ai_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_no_effort_property_when_absent(self, mock_user: AuthenticatedUser) -> None:
        captured: dict[str, Any] = {}

        async def mock_llm_call(**kwargs: Any) -> dict[str, Any]:
            captured["properties"] = get_posthog_properties()
            return {"ok": True}

        await handle_llm_request(
            request_data={"model": "test", "messages": []},
            user=mock_user,
            model="test-model",
            is_streaming=False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        properties = captured["properties"] or {}
        assert "$ai_effort" not in properties
