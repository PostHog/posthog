from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.posthog_ai.backend.services.system_prompt.prompt import POSTHOG_AI_SYSTEM_PROMPT
from products.posthog_ai.backend.services.system_prompt.service import ClaudeCodeSystemPrompt, PromptService


class TestPostHogAISystemPrompt(APIBaseTest):
    def _build(self) -> ClaudeCodeSystemPrompt:
        return PromptService(self.team, self.user).build()

    def test_build_returns_preset_append_suffix(self):
        # The object form makes the agent-server append to Claude Code's prompt (a suffix), rather
        # than the bare-string form, which would replace it.
        prompt = self._build()
        assert prompt["type"] == "preset"
        assert prompt["preset"] == "claude_code"
        assert prompt["append"].startswith(POSTHOG_AI_SYSTEM_PROMPT)

    @patch("products.posthog_ai.backend.services.system_prompt.service.approved_metric_names_for_team")
    def test_injects_approved_metric_names_with_a_cap(self, approved_metric_names_for_team) -> None:
        metric_names = [f"metric_{index}" for index in range(41)]
        approved_metric_names_for_team.return_value = metric_names

        prompt = self._build()["append"]

        assert "# Governed metrics catalog" in prompt
        assert "`metric-search`" in prompt
        assert "`data-catalog-metric-run`" in prompt
        assert "metric_39" in prompt
        assert "metric_40" not in prompt
        assert "1 more approved metric" in prompt

    @patch("products.posthog_ai.backend.services.system_prompt.service.approved_metric_names_for_team", return_value=[])
    def test_injects_an_empty_catalog_variant(self, approved_metric_names_for_team) -> None:
        prompt = self._build()["append"]

        assert "no approved metrics right now" in prompt
        assert approved_metric_names_for_team.call_args.args == (self.team, self.user)

    @patch(
        "products.posthog_ai.backend.services.system_prompt.service.approved_metric_names_for_team",
        side_effect=RuntimeError,
    )
    def test_fails_open_when_the_catalog_cannot_be_read(self, approved_metric_names_for_team) -> None:
        prompt = self._build()["append"]

        assert "could not be read" in prompt
        assert "Do not treat that failure as proof that no metric exists" in prompt
        assert approved_metric_names_for_team.call_args.args == (self.team, self.user)

    def test_includes_core_sections(self):
        prompt = self._build()["append"]
        assert "# PostHog AI" in prompt
        assert "# PostHog MCP" in prompt
        assert "# PostHog Products" in prompt
        assert "# Tone and style" in prompt
        assert "# Context blocks" in prompt
        # The MCP is reachable through its single entry point.
        assert "mcp__posthog__exec" in prompt
        # The trusted/untrusted context tags the frontend wraps messages with.
        assert "<posthog_trusted_context>" in prompt
        assert "<posthog_untrusted_context>" in prompt
        assert "AI observability** (also called AIO, LLM analytics, or LLMA)" in prompt

    def test_does_not_inject_groups_billing_core_memory_or_project_context(self):
        prompt = self._build()["append"]
        # These are reachable via the MCP server, so they are not duplicated in the system prompt.
        assert "<groups>" not in prompt
        assert "<billing_context>" not in prompt
        assert "<core_memory>" not in prompt
        assert "<project_context>" not in prompt
