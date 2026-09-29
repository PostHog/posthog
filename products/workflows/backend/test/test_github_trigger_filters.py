import json
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.compiler.bytecode import create_bytecode

from posthog.cdp.filters import hog_function_filters_to_expr

from common.hogvm.python.execute import execute_bytecode

GITHUB_EVENT_GLOBALS: dict[str, Any] = {
    "event": "$github_event_received",
    "properties": {
        "event_type": "issues",
        "action": "opened",
        "repository": "PostHog/posthog",
        "sender": "octocat",
        "bot_sender": None,
        "author_association": "MEMBER",
        "actor_access": "write",
        "title": "The database is on fire",
        "body": "everything is fine",
        "branch": None,
    },
}


def _event(**overrides):
    return {**GITHUB_EVENT_GLOBALS, "properties": {**GITHUB_EVENT_GLOBALS["properties"], **overrides}}


def _prop(key, value, operator):
    return {"key": key, "value": value, "operator": operator, "type": "event"}


class TestGithubTriggerFilters(ClickhouseTestMixin, APIBaseTest):
    """The trigger editor writes property filters, the engine runs their bytecode. These check the
    two actually agree, which is what the editor's own round-trip tests can't see."""

    def _matches(self, properties: list[dict], globals: dict | None = None) -> bool:
        expr = hog_function_filters_to_expr(filters={"properties": properties}, team=self.team, actions={})
        bytecode = json.loads(json.dumps(create_bytecode(expr).bytecode))
        return execute_bytecode(bytecode, globals or GITHUB_EVENT_GLOBALS).result is True

    @parameterized.expand(
        [
            ("the chosen repository", {"repository": "PostHog/posthog"}, True),
            ("another repository", {"repository": "PostHog/posthog.com"}, False),
        ]
    )
    def test_repository_filter(self, _name, overrides, expected):
        assert self._matches([_prop("repository", ["PostHog/posthog"], "exact")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("a listed event type", {"event_type": "issues"}, True),
            ("an unlisted event type", {"event_type": "push"}, False),
        ]
    )
    def test_several_event_types_compile_to_one_filter(self, _name, overrides, expected):
        # The control is a multi-select, so every chosen type has to match through one entry.
        properties = [_prop("event_type", ["issues", "issue_comment"], "exact")]
        assert self._matches(properties, _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("a member opened it", {"actor_access": "write"}, True),
            ("a passer-by opened it", {"actor_access": "read"}, False),
        ]
    )
    def test_write_access_only(self, _name, overrides, expected):
        # actor_access is precomputed by the emit because "trusted association, or a push" cannot be
        # expressed by comparing one property against a constant.
        assert self._matches([_prop("actor_access", ["write"], "exact")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("a person", {"bot_sender": None}, True),
            ("a bot", {"bot_sender": "dependabot[bot]"}, False),
        ]
    )
    def test_excluding_bots_keys_off_bot_sender(self, _name, overrides, expected):
        # Matching on a boolean would compare a bool against a string and never fire, so the editor
        # writes this against the nullable login instead.
        assert self._matches([_prop("bot_sender", "is_not_set", "is_not_set")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("a listed user", {"sender": "octocat"}, True),
            ("someone else", {"sender": "hacktoberfest-drive-by"}, False),
        ]
    )
    def test_specific_people(self, _name, overrides, expected):
        assert self._matches([_prop("sender", ["octocat", "hedgehog"], "exact")], _event(**overrides)) is expected

    @parameterized.expand(
        [
            ("matching title", {"title": "The database is on fire"}, True),
            ("other title", {"title": "Bump lodash"}, False),
        ]
    )
    def test_title_contains(self, _name, overrides, expected):
        assert self._matches([_prop("title", ["fire"], "icontains")], _event(**overrides)) is expected

    def test_filters_combine_with_and(self):
        properties = [
            _prop("repository", ["PostHog/posthog"], "exact"),
            _prop("actor_access", ["write"], "exact"),
        ]
        assert self._matches(properties)
        assert not self._matches(properties, _event(actor_access="read"))
