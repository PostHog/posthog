from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import time_machine

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.mcp_store.backend.connector_approvals import (
    CONNECTOR_APPROVAL_TTL_SECONDS,
    ConnectorApprovalBinding,
    consume_connector_approval,
    issue_connector_approval,
)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestConnectorApprovals(SimpleTestCase):
    def setUp(self) -> None:
        self.binding = ConnectorApprovalBinding(
            team_id=1,
            user_id=2,
            installation_id="connection-1",
            server_url="https://calendar.example.com/mcp",
            tool_name="list_events",
            arguments={"limit": 5},
            scope="canvas-1:version-1",
        )

    @parameterized.expand(
        [
            ("team_id", 3),
            ("user_id", 4),
            ("installation_id", "connection-2"),
            ("server_url", "https://other.example.com/mcp"),
            ("tool_name", "list_calendars"),
            ("arguments", {"limit": 10}),
            ("scope", "canvas-1:version-2"),
            ("scope", "canvas-2:version-1"),
        ]
    )
    def test_approval_is_bound_to_one_call(self, field_name: str, value: object) -> None:
        token = issue_connector_approval(self.binding)
        assert not consume_connector_approval(token, replace(self.binding, **cast(Any, {field_name: value})))
        assert consume_connector_approval(token, self.binding)
        assert not consume_connector_approval(token, self.binding)

    def test_invalid_and_expired_tokens_fail_closed(self) -> None:
        assert not consume_connector_approval("forged", self.binding)
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False) as clock:
            token = issue_connector_approval(self.binding)
            assert not consume_connector_approval(token + "changed", self.binding)
            clock.shift(timedelta(seconds=CONNECTOR_APPROVAL_TTL_SECONDS + 1))
            assert not consume_connector_approval(token, self.binding)
