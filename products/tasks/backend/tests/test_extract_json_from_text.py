import pytest

from parameterized import parameterized

from products.tasks.backend.services.custom_prompt_internals import extract_json_from_text

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
