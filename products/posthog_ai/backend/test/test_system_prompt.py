from typing import Any

import pytest
from posthog.test.base import APIBaseTest

from asgiref.sync import async_to_sync

from products.posthog_ai.backend.system_prompt import build_posthog_ai_system_prompt


@pytest.mark.usefixtures("unittest_snapshot")
class TestPostHogAISystemPrompt(APIBaseTest):
    snapshot: Any

    def _build(self, **kwargs: Any) -> str:
        return async_to_sync(build_posthog_ai_system_prompt)(self.team, self.user, **kwargs)

    def test_composed_prompt_baseline(self):
        prompt = self._build()
        self.snapshot.assert_match(prompt)

    def test_composed_prompt_with_context_summary(self):
        prompt = self._build(
            context_summary={
                "project_name": "Acme Analytics",
                "project_timezone": "US/Pacific",
                "region": "EU",
            }
        )
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
        assert "<capabilities_by_domain>" in prompt
        assert "<project_context>" in prompt
        assert "<product_awareness>" in prompt
