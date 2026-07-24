from django.test import SimpleTestCase

from parameterized import parameterized

from products.mcp_store.backend.policy import is_destructive_tool


class TestDestructiveToolDetection(SimpleTestCase):
    @parameterized.expand(
        [
            ("camel_case", "deleteUser", "", True),
            ("snake_case", "bulk_delete_users", "", True),
            ("kebab_case", "archive-project", "", True),
            ("description_conjugation", "manage_issue", "Deletes an issue permanently.", True),
            ("description_gerund", "manage_issue", "Removing stale issues.", True),
            ("substring_dropdown", "list_dropdown_options", "", False),
            ("substring_preset", "get_preset", "", False),
            ("substring_swipe", "swipe_card", "", False),
            ("description_substring", "list_options", "Displays preset choices.", False),
        ]
    )
    def test_detects_only_destructive_tokens(
        self, _name: str, tool_name: str, description: str, expected: bool
    ) -> None:
        assert is_destructive_tool(tool_name, description) is expected
