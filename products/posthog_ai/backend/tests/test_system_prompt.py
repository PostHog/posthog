from posthog.test.base import APIBaseTest

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

    def test_instructs_the_agent_to_inspect_the_complete_metric_catalog(self) -> None:
        prompt = self._build()["append"]

        assert "# Governed metrics catalog" in prompt
        assert "`metric-list`" in prompt
        assert "`metric-describe`" in prompt
        assert "`data-catalog-metric-run`" in prompt
        assert "complete governed catalog" in prompt
        assert "its shape, not whether its noun sounds like a KPI" in prompt
        assert "a count or volume of X per day, hour, or week" in prompt
        assert "a rate or percentage of X" in prompt
        assert "an average, percentile, or latency of X" in prompt
        assert "a cost per X" in prompt
        assert "a conversion between two events" in prompt
        assert "are not substitutes for `metric-list`" in prompt
        assert "product skill's query recipe does not exempt" in prompt
        assert "Never present a `proposed` or drifted metric's result as the answer" in prompt
        assert "Derive from an approved metric when one covers the same measure" in prompt
        assert "otherwise derive the number yourself" in prompt

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
