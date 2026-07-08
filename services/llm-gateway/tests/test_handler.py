from collections.abc import Iterator
from typing import Any

import pytest

from llm_gateway.api.handler import ANTHROPIC_CONFIG, _extract_effort, handle_llm_request
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.request_context import effort_var, get_effort


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

    def test_whitespace_only_effort_is_none(self) -> None:
        assert _extract_effort({"reasoning_effort": "   "}) is None


class TestEffortInstrumentation:
    @pytest.fixture(autouse=True)
    def reset_effort(self) -> Iterator[None]:
        token = effort_var.set(None)
        yield
        effort_var.reset(token)

    @pytest.mark.asyncio
    async def test_effort_lands_on_request_context(self, authenticated_user: AuthenticatedUser) -> None:
        captured: dict[str, Any] = {}

        async def mock_llm_call(**kwargs: Any) -> dict[str, Any]:
            # set_effort runs before the provider call, so the effort is visible on the
            # context the PostHog callback later reads.
            captured["effort"] = get_effort()
            return {"ok": True}

        await handle_llm_request(
            request_data={"model": "test", "messages": [], "output_config": {"effort": "medium"}},
            user=authenticated_user,
            model="test-model",
            is_streaming=False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert captured["effort"] == "medium"

    @pytest.mark.asyncio
    async def test_no_effort_when_absent(self, authenticated_user: AuthenticatedUser) -> None:
        captured: dict[str, Any] = {}

        async def mock_llm_call(**kwargs: Any) -> dict[str, Any]:
            captured["effort"] = get_effort()
            return {"ok": True}

        await handle_llm_request(
            request_data={"model": "test", "messages": []},
            user=authenticated_user,
            model="test-model",
            is_streaming=False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert captured["effort"] is None

    @pytest.mark.asyncio
    async def test_stale_effort_is_reset_when_absent(self, authenticated_user: AuthenticatedUser) -> None:
        # A value from a prior request must not leak into one that sets no effort:
        # handle_llm_request sets it unconditionally (None when absent).
        effort_var.set("high")
        captured: dict[str, Any] = {}

        async def mock_llm_call(**kwargs: Any) -> dict[str, Any]:
            captured["effort"] = get_effort()
            return {"ok": True}

        await handle_llm_request(
            request_data={"model": "test", "messages": []},
            user=authenticated_user,
            model="test-model",
            is_streaming=False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=mock_llm_call,
        )

        assert captured["effort"] is None
