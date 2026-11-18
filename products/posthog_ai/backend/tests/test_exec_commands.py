import unittest

from products.posthog_ai.backend.exec_commands import normalize_tool_name


class TestNormalizeToolName(unittest.TestCase):
    def test_strips_mcp_prefix(self):
        self.assertEqual(normalize_tool_name("mcp__posthog__query-trends"), "query-trends")

    def test_passes_through_bare_names(self):
        self.assertEqual(normalize_tool_name("query-trends"), "query-trends")

    def test_handles_empty_and_none(self):
        self.assertEqual(normalize_tool_name(None), "")
        self.assertEqual(normalize_tool_name(""), "")
