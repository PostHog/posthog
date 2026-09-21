from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import exceptions

from products.logs.backend.pattern_response import (
    MCP_MAX_PATTERN_CHARS,
    MCP_PATTERN_LIMIT,
    MIN_PATTERN_CHARS,
    bound_patterns_response,
    max_pattern_limit,
    parse_limit,
    parse_max_pattern_chars,
)


def _pattern(**overrides) -> dict:
    return {
        "pattern": "db connection failed",
        "count": 3,
        "match_patterns": [],
        "match_regex": None,
        "match_literal": None,
        **overrides,
    }


class TestPatternResponseParams(SimpleTestCase):
    @parameterized.expand(
        [
            (None, False, max_pattern_limit()),
            (None, True, MCP_PATTERN_LIMIT),
            (5, True, 5),
            ("5", False, 5),
            (100000, False, max_pattern_limit()),
        ]
    )
    def test_parse_limit(self, raw: object, over_mcp: bool, expected: int) -> None:
        self.assertEqual(parse_limit(raw, over_mcp=over_mcp), expected)

    @parameterized.expand(
        [
            (None, False, 0),
            (None, True, MCP_MAX_PATTERN_CHARS),
            (0, True, 0),
            (MIN_PATTERN_CHARS, True, MIN_PATTERN_CHARS),
        ]
    )
    def test_parse_max_pattern_chars(self, raw: object, over_mcp: bool, expected: int) -> None:
        self.assertEqual(parse_max_pattern_chars(raw, over_mcp=over_mcp), expected)

    @parameterized.expand([(0,), (-1,), ("many",), (True,)])
    def test_parse_limit_rejects(self, raw: object) -> None:
        with self.assertRaises(exceptions.ValidationError):
            parse_limit(raw, over_mcp=False)

    @parameterized.expand([(-1,), (MIN_PATTERN_CHARS - 1,), ("some",)])
    def test_parse_max_pattern_chars_rejects(self, raw: object) -> None:
        with self.assertRaises(exceptions.ValidationError):
            parse_max_pattern_chars(raw, over_mcp=False)


class TestBoundPatternsResponse(SimpleTestCase):
    def test_keeps_the_highest_volume_groups_and_counts_the_rest(self) -> None:
        results = {"patterns": [_pattern(count=count) for count in (9, 8, 7)], "total_count": 24}

        bounded = bound_patterns_response(results, limit=2, max_pattern_chars=0)

        self.assertEqual([pattern["count"] for pattern in bounded["patterns"]], [9, 8])
        self.assertEqual(bounded["returned_pattern_count"], 2)
        self.assertEqual(bounded["omitted_pattern_count"], 1)
        self.assertEqual(bounded["total_count"], 24)

    def test_unbounded_response_is_unchanged_apart_from_the_bound_report(self) -> None:
        pattern = _pattern(pattern="x" * 5000, match_patterns=["x" * 5000], match_regex="x" * 5000)

        bounded = bound_patterns_response({"patterns": [pattern]}, limit=200, max_pattern_chars=0)

        self.assertEqual(bounded["patterns"][0]["pattern"], "x" * 5000)
        self.assertEqual(bounded["patterns"][0]["match_regex"], "x" * 5000)
        self.assertFalse(bounded["patterns"][0]["pattern_truncated"])
        self.assertEqual(bounded["omitted_pattern_count"], 0)

    def test_cuts_a_long_template_to_the_budget_and_marks_it(self) -> None:
        results = {"patterns": [_pattern(pattern="Query failed: " + "x" * 4000)]}

        pattern = bound_patterns_response(results, limit=20, max_pattern_chars=200)["patterns"][0]

        self.assertEqual(len(pattern["pattern"]), 200)
        self.assertTrue(pattern["pattern"].startswith("Query failed: "))
        self.assertIn("maxPatternChars=0", pattern["pattern"])
        self.assertTrue(pattern["pattern_truncated"])

    def test_keeps_whole_members_of_the_exact_pivot_within_the_budget(self) -> None:
        members = ["a" * 60, "b" * 60, "c" * 60]
        results = {"patterns": [_pattern(match_patterns=members)]}

        pattern = bound_patterns_response(results, limit=20, max_pattern_chars=100)["patterns"][0]

        self.assertEqual(pattern["match_patterns"], ["a" * 60])
        self.assertEqual(pattern["match_patterns_omitted"], 2)

    def test_keeps_the_first_member_even_when_it_alone_is_over_budget(self) -> None:
        results = {"patterns": [_pattern(match_patterns=["a" * 4000, "b" * 4000])]}

        pattern = bound_patterns_response(results, limit=20, max_pattern_chars=100)["patterns"][0]

        self.assertEqual(pattern["match_patterns"], ["a" * 4000])
        self.assertEqual(pattern["match_patterns_omitted"], 1)

    def test_drops_an_over_budget_regex_but_cuts_the_literal(self) -> None:
        results = {"patterns": [_pattern(match_regex="^Query failed: " + "x" * 4000, match_literal="Q" * 4000)]}

        pattern = bound_patterns_response(results, limit=20, max_pattern_chars=100)["patterns"][0]

        self.assertIsNone(pattern["match_regex"])
        self.assertTrue(pattern["match_regex_omitted"])
        self.assertEqual(pattern["match_literal"], "Q" * 100)
        self.assertTrue(pattern["match_literal_truncated"])
