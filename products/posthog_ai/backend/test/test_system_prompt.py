from typing import Any

import pytest
from posthog.test.base import APIBaseTest

from products.posthog_ai.backend.system_prompt import PromptService


@pytest.mark.usefixtures("unittest_snapshot")
class TestPostHogAISystemPrompt(APIBaseTest):
    snapshot: Any

    def _build(self) -> str:
        return PromptService(self.team, self.user).build()

    def test_composed_prompt_baseline(self):
        prompt = self._build()
        self.snapshot.assert_match(prompt)

    def test_does_not_inject_groups_billing_or_core_memory(self):
        prompt = self._build()
        assert "<groups>" not in prompt
        assert "<billing_context>" not in prompt
        assert "<core_memory>" not in prompt
        # The groups placeholder inside basic_functionality resolves to empty.
        assert "{{{groups_prompt}}}" not in prompt
        assert "{{groups_prompt}}" not in prompt

    def test_includes_core_sections(self):
        prompt = self._build()
        assert "<identity>" in prompt
        assert "<capabilities>" in prompt
        assert "<product_awareness>" in prompt
        # Project context is injected by the MCP server, not built into the system prompt.
        assert "<project_context>" not in prompt
