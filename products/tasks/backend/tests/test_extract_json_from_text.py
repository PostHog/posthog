import pytest

from parameterized import parameterized

from products.tasks.backend.logic.services.custom_prompt_internals import extract_json_from_text

EXPECTED = {"answer": "hello world"}
JSON_STR = '{"answer": "hello world"}'


class TestExtractJsonFromText:
    @parameterized.expand(
        [
            ("bare_json", JSON_STR),
            ("generic_code_block", f"```\n{JSON_STR}\n```"),
            ("json_code_block", f"```json\n{JSON_STR}\n```"),
            ("text_above_bare_json", f"Here is your answer:\n{JSON_STR}"),
            ("text_above_generic_block", f"Here is your answer:\n```\n{JSON_STR}\n```"),
            ("text_above_json_block", f"Here is your answer:\n```json\n{JSON_STR}\n```"),
            ("text_above_and_below_bare_json", f"Here is your answer:\n{JSON_STR}\nHope that helps!"),
            ("text_above_and_below_generic_block", f"Here is your answer:\n```\n{JSON_STR}\n```\nHope that helps!"),
            ("text_above_and_below_json_block", f"Here is your answer:\n```json\n{JSON_STR}\n```\nHope that helps!"),
        ]
    )
    def test_extracts_json(self, _name, text):
        assert extract_json_from_text(text, label="test") == EXPECTED

    def test_none_raises_value_error(self):
        with pytest.raises(ValueError, match="is None"):
            extract_json_from_text(None, label="test")

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            extract_json_from_text("not json at all", label="test")

    @parameterized.expand(
        [
            ("empty_string", "", "empty or whitespace-only"),
            ("whitespace_only", "   \n\t ", "empty or whitespace-only"),
            ("prose_only", "I checked everything and found nothing worth surfacing.", "prose with no JSON object"),
            ("fenced_invalid", "```json\nnot: valid json\n```", "code fence but its contents did not parse"),
        ]
    )
    def test_classifies_unparseable_text(self, _name, text, expected_message):
        with pytest.raises(ValueError, match=expected_message):
            extract_json_from_text(text, label="initial turn")

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
