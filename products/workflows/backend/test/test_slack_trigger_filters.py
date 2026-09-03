import json
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.compiler.bytecode import create_bytecode

from posthog.cdp.filters import hog_function_filters_to_expr

from common.hogvm.python.execute import execute_bytecode

SLACK_MESSAGE_GLOBALS: dict[str, Any] = {
    "event": "$slack_message_received",
    "properties": {
        "channel": "C0ALERTS",
        "channel_type": "channel",
        "slack_team_id": "T123",
        "user": "U123",
        "bot_id": None,
        "app_id": None,
        "subtype": None,
        "text": "the database is on fire",
        "ts": "1700000000.000100",
        "thread_ts": None,
        "is_thread_reply": False,
        "is_ext_shared_channel": False,
    },
}


def _event(**overrides):
    return {**SLACK_MESSAGE_GLOBALS, "properties": {**SLACK_MESSAGE_GLOBALS["properties"], **overrides}}


def _prop(key, value, operator):
    return {"key": key, "value": value, "operator": operator, "type": "event"}


class TestSlackTriggerFilters(ClickhouseTestMixin, APIBaseTest):
    """The trigger editor writes property filters, the engine runs their bytecode. These check the
    two actually agree, which is what the editor's own round-trip tests can't see."""

    def _matches(self, properties: list[dict], globals: dict | None = None) -> bool:
        expr = hog_function_filters_to_expr(filters={"properties": properties}, team=self.team, actions={})
        bytecode = json.loads(json.dumps(create_bytecode(expr).bytecode))
        return execute_bytecode(bytecode, globals or SLACK_MESSAGE_GLOBALS).result is True

    def test_channel_filter_matches_the_bare_id(self):
        assert self._matches([_prop("channel", ["C0ALERTS"], "exact")])

    def test_channel_filter_does_not_match_the_picker_composite(self):
        # The picker identifies a channel as `C123|#name`; storing that verbatim compiled a filter
        # that could never match, and the editor's round-trip tests were blind to it.
        assert not self._matches([_prop("channel", ["C0ALERTS|#alerts"], "exact")])

    @parameterized.expand(
        [
            ("a person posted", {}, True),
            ("an app posted", {"bot_id": "B42"}, False),
        ]
    )
    def test_people_only_excludes_apps(self, _name, overrides, expected):
        assert self._matches([_prop("bot_id", "is_not_set", "is_not_set")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("an app posted", {"bot_id": "B42"}, True),
            ("a person posted", {}, False),
        ]
    )
    def test_apps_only_excludes_people(self, _name, overrides, expected):
        assert self._matches([_prop("bot_id", "is_set", "is_set")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("a listed user", {"user": "U123"}, True),
            ("someone else", {"user": "U999"}, False),
        ]
    )
    def test_specific_people(self, _name, overrides, expected):
        assert self._matches([_prop("user", ["U123", "U456"], "exact")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("a top-level post", {"thread_ts": None}, True),
            ("a thread reply", {"thread_ts": "1699999999.000000"}, False),
        ]
    )
    def test_ignoring_thread_replies_keys_off_thread_ts(self, _name, overrides, expected):
        # Matching on the is_thread_reply boolean instead would compare a bool against a string and
        # never fire, so the editor deliberately writes this one against thread_ts.
        assert self._matches([_prop("thread_ts", "is_not_set", "is_not_set")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("matching text", {"text": "the database is on fire"}, True),
            ("other text", {"text": "deploy finished"}, False),
        ]
    )
    def test_message_text_contains(self, _name, overrides, expected):
        assert self._matches([_prop("text", ["fire"], "icontains")], _event(**overrides)) is expected

    def test_filters_combine_with_and(self):
        properties = [
            _prop("channel", ["C0ALERTS"], "exact"),
            _prop("bot_id", "is_not_set", "is_not_set"),
        ]
        assert self._matches(properties)
        assert not self._matches(properties, _event(bot_id="B42"))
