from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.posthog_ai.backend.models.assistant import CoreMemory
from products.posthog_ai.backend.services.system_prompt.prompt import POSTHOG_AI_SYSTEM_PROMPT
from products.posthog_ai.backend.services.system_prompt.service import ClaudeCodeSystemPrompt, PromptService


class TestPostHogAISystemPrompt(APIBaseTest):
    def _build(self) -> ClaudeCodeSystemPrompt:
        return PromptService(self.team, self.user).build()

    def test_build_returns_preset_append_suffix(self):
        # The object form makes the agent-server append to Claude Code's prompt (a suffix), rather
        # than the bare-string form, which would replace it.
        built = self._build()
        assert built["type"] == "preset"
        assert built["preset"] == "claude_code"
        assert built["append"].startswith(POSTHOG_AI_SYSTEM_PROMPT)

    def test_injects_saved_core_memory(self):
        # No MCP tool exposes core memory, so the sandbox agent only ever sees it if it's here.
        CoreMemory.objects.create(team=self.team, text="Acme's orgs are named in `organizationName`.")
        assert "Acme's orgs are named in `organizationName`." in self._build()["append"]

    def test_states_memory_is_read_only_when_none_is_saved(self):
        # Without this the agent offers to save facts to a memory it has no write path to.
        append = self._build()["append"]
        assert "<core_memory>" in append
        assert "No facts are saved for this project yet." in append
        assert "never offer to save, update, or remember anything" in append

    def test_omits_core_memory_when_disabled_for_the_organization(self):
        with patch("products.posthog_ai.backend.services.core_memory.is_core_memory_disabled", return_value=True):
            assert self._build()["append"] == POSTHOG_AI_SYSTEM_PROMPT

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

    def test_does_not_inject_groups_billing_or_project_context(self):
        prompt = self._build()["append"]
        # These are reachable via the MCP server, so they are not duplicated in the system prompt.
        assert "<groups>" not in prompt
        assert "<billing_context>" not in prompt
        assert "<project_context>" not in prompt
