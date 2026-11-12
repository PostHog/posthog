from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.workflows.backend.services.resend_import import drafts


def _automation(automation_id: str) -> dict[str, Any]:
    return {
        "id": automation_id,
        "name": f"Invented {automation_id}",
        "steps": [
            {"key": "start", "type": "trigger", "config": {"event_name": "user.created"}},
            {"key": "wait", "type": "delay", "config": {"duration": "1 hour"}},
        ],
        "connections": [{"from": "start", "to": "wait"}],
    }


class TestResendAutomationDrafts(BaseTest):
    def test_access_rules_load_once_for_a_page_of_automations(self) -> None:
        with patch.object(drafts, "UserAccessControl", wraps=drafts.UserAccessControl) as access:
            with drafts.reuse_import_access():
                results = [
                    drafts.import_resend_automation(self.team.id, self.user.id, _automation(automation_id), {})
                    for automation_id in ("a1", "a2")
                ]

        assert [result.status for result in results] == ["created", "created"]
        assert access.call_count == 1
