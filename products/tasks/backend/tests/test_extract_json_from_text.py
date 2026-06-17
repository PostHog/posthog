import pytest

from parameterized import parameterized

from products.tasks.backend.services.custom_prompt_internals import AgentOutputNotJSONError, extract_json_from_text

EXPECTED = {"answer": "hello world"}
JSON_STR = '{"answer": "hello world"}'
NESTED_JSON_STR = '{"answer": {"nested": "hello world"}}'
NESTED_EXPECTED = {"answer": {"nested": "hello world"}}


class TestExtractJsonFromText:
    @parameterized.expand(
        [
            ("bare_json", JSON_STR, EXPECTED),
            ("generic_code_block", f"```\n{JSON_STR}\n```", EXPECTED),
            ("json_code_block", f"```json\n{JSON_STR}\n```", EXPECTED),
            ("bare_object_in_prose", f"Here is your answer:\n{JSON_STR}\nHope that helps!", EXPECTED),
            ("nested_braces", f"Sure:\n{NESTED_JSON_STR}", NESTED_EXPECTED),
        ]
    )
    def test_extracts_json_unchanged(self, _name, text, expected):
        assert extract_json_from_text(text, label="test") == expected

    @parameterized.expand(
        [
            ("no_json_prose", "I could not complete the request, sorry."),
            ("empty_string", ""),
            ("provider_error_text", "API Error: 429 rate_limit_error"),
        ]
    )
    def test_no_json_raises_typed_error(self, _name, text):
        with pytest.raises(AgentOutputNotJSONError) as exc_info:
            extract_json_from_text(text, label="repo-selection")
        assert exc_info.value.label == "repo-selection"
        # Snippet is bounded and carries the offending text (truncated to SNIPPET_CHARS).
        assert exc_info.value.snippet == text[: AgentOutputNotJSONError.SNIPPET_CHARS]
        # Subclasses ValueError so existing `except ValueError` callers still catch it.
        assert isinstance(exc_info.value, ValueError)

    def test_snippet_is_bounded(self):
        long_text = "x" * 5000
        with pytest.raises(AgentOutputNotJSONError) as exc_info:
            extract_json_from_text(long_text, label="test")
        assert len(exc_info.value.snippet) == AgentOutputNotJSONError.SNIPPET_CHARS

    def test_none_raises_value_error(self):
        with pytest.raises(ValueError, match="is None"):
            extract_json_from_text(None, label="test")

    @parameterized.expand(
        [
            ("bare_array", "[1, 2, 3]", [1, 2, 3]),
            ("array_with_whitespace", "  [1, 2, 3]  ", [1, 2, 3]),
        ]
    )
    def test_still_parses_non_object_json(self, _name, text, expected):
        # The last-resort path must keep parsing valid top-level JSON that isn't an object
        # (arrays, scalars) — only genuinely unparseable text should raise.
        assert extract_json_from_text(text, label="test") == expected
