from posthog.test.base import BaseTest

from parameterized import parameterized

from products.logs.backend.logs_query_runner import parse_search_tokens


class TestParseSearchTokens(BaseTest):
    @parameterized.expand(
        [
            ("single positive", "error", [("positive", "error")]),
            ("single negative", "!error", [("negative", "error")]),
            ("multiple positive AND", "error warning", [("positive", "error"), ("positive", "warning")]),
            ("multiple negative", "!error !warning", [("negative", "error"), ("negative", "warning")]),
            ("mixed positive and negative", "error !warning", [("positive", "error"), ("negative", "warning")]),
            ("quoted phrase", '"hello world"', [("positive", "hello world")]),
            ("negative quoted phrase", '!"hello world"', [("negative", "hello world")]),
            ("standalone bang ignored", "!", []),
            ("double bang ignored", "!!", []),
            ("standalone bang with tokens", "error ! warning", [("positive", "error"), ("positive", "warning")]),
            ("multiple spaces", "error    warning", [("positive", "error"), ("positive", "warning")]),
            ("malformed quotes fallback", '"unclosed quote', [("positive", '"unclosed'), ("positive", "quote")]),
        ]
    )
    def test_parse_search_tokens(self, _name: str, search_term: str, expected: list[tuple[str, str]]):
        result = parse_search_tokens(search_term)
        self.assertEqual(result, expected)
