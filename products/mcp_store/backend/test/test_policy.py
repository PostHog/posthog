from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.mcp_store.backend.policy import is_destructive_tool, is_read_only_connector_tool, member_preset_team_state


class TestDestructiveToolDetection(SimpleTestCase):
    @parameterized.expand(
        [
            ("camel_case", "deleteUser", None, True),
            ("snake_case", "bulk_delete_users", None, True),
            ("kebab_case", "archive-project", None, True),
            ("substring_dropdown", "list_dropdown_options", None, False),
            ("substring_preset", "get_preset", None, False),
            ("substring_swipe", "swipe_card", None, False),
            ("hint_escalates_neutral_name", "manage_issue", {"destructiveHint": True}, True),
            ("hint_never_clears_name_match", "delete_user", {"destructiveHint": False}, True),
            ("hint_absent", "manage_issue", {}, False),
            ("hint_non_bool_ignored", "manage_issue", {"destructiveHint": "true"}, False),
            ("hint_truthy_int_ignored", "manage_issue", {"destructiveHint": 1}, False),
        ]
    )
    def test_detects_destructive_names_and_hints(
        self, _name: str, tool_name: str, annotations: dict[str, Any] | None, expected: bool
    ) -> None:
        assert is_destructive_tool(tool_name, annotations) is expected


class TestReadOnlyToolDetection(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_verb_with_hint", "list_issues", {"readOnlyHint": True}, True),
            ("camel_case", "getIssue", {"readOnlyHint": True}, True),
            ("hint_absent", "list_issues", {}, False),
            ("hint_non_bool_ignored", "list_issues", {"readOnlyHint": "true"}, False),
            ("write_verb_ignores_hint", "create_issue", {"readOnlyHint": True}, False),
            ("chained_write_verb", "get_and_update_issue", {"readOnlyHint": True}, False),
            ("destructive_hint_wins", "get_issue", {"readOnlyHint": True, "destructiveHint": True}, False),
        ]
    )
    def test_requires_read_verb_and_hint(
        self, _name: str, tool_name: str, annotations: dict[str, Any], expected: bool
    ) -> None:
        assert is_read_only_connector_tool(tool_name, annotations) is expected

    @parameterized.expand(
        [
            ("ask_gates_on_hint", "ask", {"destructiveHint": True}, "needs_approval"),
            ("block_gates_on_hint", "block", {"destructiveHint": True}, "do_not_use"),
            ("block_allows_without_signal", "block", None, "approved"),
        ]
    )
    def test_presets_thread_annotations_through(
        self, _name: str, preset: str, annotations: dict[str, Any] | None, expected: str
    ) -> None:
        assert member_preset_team_state(preset, "manage_issue", annotations) == expected
