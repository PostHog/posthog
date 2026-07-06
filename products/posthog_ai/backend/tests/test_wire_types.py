from typing import Any

import unittest

from parameterized import parameterized
from pydantic import TypeAdapter

from products.posthog_ai.backend.wire_types import (
    METHOD_USER_MESSAGE,
    NotificationFrame,
    UnknownFrame,
    UserMessageParams,
    is_user_message_params,
    parse_log_entry,
)

TIMESTAMP = "2026-06-11T09:00:00.000000+00:00"


def _notification(method: str, params: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    return {"type": "notification", "timestamp": TIMESTAMP, "notification": body}


class TestWireTypes(unittest.TestCase):
    @parameterized.expand(
        [
            ("plain_string", {"content": "Why did checkout conversion drop last week?"}),
            ("content_blocks", {"content": [{"type": "text", "text": "Why did checkout conversion drop?"}]}),
        ]
    )
    def test_user_message_entries_classify_guard_and_validate_strictly(
        self, _name: str, params: dict[str, Any]
    ) -> None:
        parsed = parse_log_entry(_notification(METHOD_USER_MESSAGE, params))
        assert isinstance(parsed, NotificationFrame)
        assert is_user_message_params(parsed.notification.params, parsed.notification.method)
        # Strict validation of the adapter-owned payload happens here, never in production code —
        # a drifted shape fails this suite instead of raising mid-log-walk.
        TypeAdapter(UserMessageParams).validate_python(parsed.notification.params, strict=True)

    @parameterized.expand(
        [
            ("other_method", _notification("_posthog/turn_complete", {"stopReason": "end_turn"})),
            ("no_params", _notification(METHOD_USER_MESSAGE)),
            (
                "string_params",
                {"type": "notification", "notification": {"method": METHOD_USER_MESSAGE, "params": "not-an-object"}},
            ),
        ]
    )
    def test_guard_rejects_non_user_message_payloads(self, _name: str, entry: dict[str, Any]) -> None:
        parsed = parse_log_entry(entry)
        assert isinstance(parsed, NotificationFrame)
        assert not is_user_message_params(parsed.notification.params, parsed.notification.method)

    @parameterized.expand(
        [
            ("unknown_type", {"type": "telemetry_v2", "payload": {"value": 5120}}),
            ("missing_type", {"status": "in_progress", "note": "frame with no type discriminant"}),
            ("task_run_state", {"type": "task_run_state", "status": "in_progress"}),
            ("non_object_body", {"type": "notification", "notification": "oops"}),
        ]
    )
    def test_unrecognized_entries_classify_as_unknown_without_raising(self, _name: str, entry: dict[str, Any]) -> None:
        parsed = parse_log_entry(entry)
        assert isinstance(parsed, UnknownFrame)
        assert parsed.raw == entry

    def test_extra_envelope_fields_are_tolerated(self) -> None:
        entry = _notification(METHOD_USER_MESSAGE, {"content": "hi", "futureField": True})
        entry["futureEnvelopeField"] = "later"
        parsed = parse_log_entry(entry)
        assert isinstance(parsed, NotificationFrame)
        assert is_user_message_params(parsed.notification.params, parsed.notification.method)
