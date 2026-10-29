import json
import time
from typing import Any

import time_machine
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import JsonValue

from posthog.models import Team

from products.cdp.backend.facade.api import compile_hog
from products.mcp_events.backend.logic.destination import DESTINATION_HOG, MAX_EVENT_BYTES
from products.mcp_events.backend.logic.properties import MCPEventPropertyAccess

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.utils import UncaughtHogVMException

GROUP_TYPES = [
    {"group_type_index": 0, "group_type": "organization"},
    {"group_type_index": 1, "group_type": "project"},
]


class TestMCPEventDestinationHog(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(time_machine.travel("2026-01-01T00:00:00Z", tick=False))
        self.bytecode = compile_hog(DESTINATION_HOG, "destination")
        self.fetch = MagicMock(return_value={"status": 200, "body": {}})

    def run_hog(
        self,
        properties: JsonValue,
        redaction: dict[str, JsonValue],
        max_bytes: int = MAX_EVENT_BYTES,
        expires_at: int | None = None,
    ) -> Any:
        inputs = {
            "url": "https://example.com/callback",
            "signing_secret": "whsec_example",
            "subscription_id": "example-subscription",
            "restricted_properties": redaction,
            "max_bytes": max_bytes,
            "expires_at": expires_at if expires_at is not None else int(time.time() * 1000) + 3600000,
            "envelope": {
                "eventId": "example-event",
                "name": "posthog.event_captured",
                "timestamp": "2026-01-01T00:00:00Z",
                "data": {"event": "example_event", "distinct_id": "sample-user", "properties": properties},
            },
        }
        return execute_bytecode(self.bytecode, {"inputs": inputs}, functions={"fetch": self.fetch})

    def delivered_properties(self) -> JsonValue:
        url, options = self.fetch.call_args.args
        self.assertEqual(url, "https://example.com/callback")
        self.assertEqual(options["standard_webhooks"], {"secret_input": "signing_secret"})
        self.assertEqual(options["headers"]["X-MCP-Subscription-Id"], "example-subscription")
        body = json.loads(options["body"])
        self.assertEqual(body["eventId"], "example-event")
        self.assertIsNone(body["cursor"])
        return body["data"]["properties"]

    @parameterized.expand(
        [
            ("no_restrictions", {"plan": "visible"}, set(), {"plan": "visible"}),
            (
                "nested_descendants",
                {"customer": {"ssn.part": "hidden", "ssn%2Epart": "hidden", "name": "visible"}},
                {"customer.ssn"},
                {"customer": {"name": "visible"}},
            ),
            (
                "top_level_and_dotted_aliases",
                {"customer": {"ssn": "x"}, "customer.ssn": "x", "customer%2Essn": "x", "customer_name": "visible"},
                {"customer"},
                {"customer_name": "visible"},
            ),
            (
                "group_type_alias",
                {"$groups": {"organization": "x", "project": "visible"}, "$group_0": "x", "$group_1": "visible"},
                {"$groups.organization"},
                {"$groups": {"project": "visible"}, "$group_1": "visible"},
            ),
            (
                "group_index_alias",
                {"$groups": {"organization": "x", "project": "visible"}, "$group_0": "x", "$group_1": "visible"},
                {"$group_0"},
                {"$groups": {"project": "visible"}, "$group_1": "visible"},
            ),
            (
                "all_groups",
                {"$groups": {"organization": "x"}, "$group_0": "x", "$group_4": "x", "plan": "visible"},
                {"$groups"},
                {"plan": "visible"},
            ),
            (
                "deep_path_drops_the_parent",
                {"customer": {"profile": {"ssn": "x"}}, "plan": "visible"},
                {"customer.profile.ssn"},
                {"plan": "visible"},
            ),
            (
                "nested_rule_on_a_list_drops_the_parent",
                {"items": [{"secret": "x", "public": "visible"}], "plan": "visible"},
                {"items.secret"},
                {"plan": "visible"},
            ),
            (
                "all_flags",
                {
                    "$feature/secret": True,
                    "$active_feature_flags": ["secret", "public"],
                    "$feature_flags": {"secret": True, "public": False},
                    "plan": "visible",
                },
                {"$feature_flags"},
                {"plan": "visible"},
            ),
            (
                "one_flag",
                {
                    "$feature/secret": True,
                    "$feature/public": False,
                    "$active_feature_flags": ["secret", "public"],
                    "$feature_flags": {"secret": True, "public": False},
                },
                {"$feature/secret"},
                {"$feature/public": False, "$active_feature_flags": ["public"], "$feature_flags": {"public": False}},
            ),
        ]
    )
    def test_hog_and_preview_redact_the_same_properties(
        self, _name: str, properties: dict[str, JsonValue], restricted: set[str], expected: dict[str, JsonValue]
    ) -> None:
        with patch(
            "products.mcp_events.backend.logic.properties.get_group_types_for_project", return_value=GROUP_TYPES
        ):
            names = MCPEventPropertyAccess.with_group_aliases(restricted, team=Team(project_id=1))
        redaction = MCPEventPropertyAccess.redaction(sorted(names))
        self.run_hog(properties, redaction)
        self.assertEqual(self.delivered_properties(), expected)
        self.assertEqual(MCPEventPropertyAccess.redact(properties, redaction), expected)

    @parameterized.expand([("oversized", 200, 10), ("rejected", 410, MAX_EVENT_BYTES)])
    def test_failed_delivery_raises(self, _name: str, status: int, max_bytes: int) -> None:
        self.fetch.return_value = {"status": status, "body": {}}
        with self.assertRaises(UncaughtHogVMException):
            self.run_hog({"plan": "visible"}, MCPEventPropertyAccess.redaction([]), max_bytes=max_bytes)
        self.assertEqual(self.fetch.called, status != 200)

    @parameterized.expand([-1, 0, 1])
    def test_delivery_checks_the_granted_expiry(self, offset_ms: int) -> None:
        expiry = int(time.time() * 1000) + offset_ms
        if offset_ms <= 0:
            with self.assertRaises(UncaughtHogVMException):
                self.run_hog({}, MCPEventPropertyAccess.redaction([]), expires_at=expiry)
            self.fetch.assert_not_called()
        else:
            self.run_hog({}, MCPEventPropertyAccess.redaction([]), expires_at=expiry)
            self.fetch.assert_called_once()
            self.assertEqual(self.fetch.call_args.args[1]["expires_at"], expiry)

    @parameterized.expand(["a", "測", "😀"])
    def test_payload_limit_counts_utf8_bytes(self, character: str) -> None:
        properties: dict[str, JsonValue] = {"text": character * 50}
        self.run_hog(properties, MCPEventPropertyAccess.redaction([]))
        size = len(self.fetch.call_args.args[1]["body"].encode("utf-8"))
        self.fetch.reset_mock()
        self.run_hog(properties, MCPEventPropertyAccess.redaction([]), max_bytes=size)
        self.fetch.assert_called_once()
        self.fetch.reset_mock()
        with self.assertRaises(UncaughtHogVMException):
            self.run_hog(properties, MCPEventPropertyAccess.redaction([]), max_bytes=size - 1)
        self.fetch.assert_not_called()
