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
            ("brace_in_text_below_bare_json", f"{JSON_STR}\nReplace {{name}} before you send it."),
            ("unmatched_brace_in_text_above_bare_json", f"The reply must start with {{ — here it is:\n{JSON_STR}"),
            ("cut_off_object_after_bare_json", f'{JSON_STR}\nNext: {{"step": [1, 2'),
            ("cut_off_object_after_json_block", f"```json\n{JSON_STR}\n```\nthen {{"),
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
            # A reply cut off mid-object holds inner objects that parse on their own. Returning one
            # gives the caller a fragment, and the schema error that follows blames a missing field.
            ("truncated_with_whole_inner_object", '{"duplicates": [{"id": "1-3-3"}', "Output truncated"),
            ("truncated_mid_value", '{"duplicates": [{"id": "1-3', "Output truncated"),
            (
                "truncated_answer_after_a_matching_sample",
                'Sample: {"answer": 1}\nFinal:\n{"answer": "hel',
                "Output truncated",
                {"answer"},
            ),
        ]
    )
    def test_classifies_unparseable_text(self, _name, text, expected_message, required_keys=None):
        with pytest.raises(ValueError, match=expected_message):
            extract_json_from_text(text, label="initial turn", required_keys=required_keys)

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

    @parameterized.expand(
        [
            (
                "error_envelope_before_answer",
                f'{{"type": "error", "message": "query failed"}}\n{JSON_STR}',
            ),
            (
                "tool_call_and_sample_payload_before_answer",
                f'{{"tool": "execute-sql"}}\nSample: {{"answer": 1, "other": 2}}\nFinal:\n{JSON_STR}',
            ),
            ("answer_in_fence_after_envelope", f'{{"error": "boom"}}\n```json\n{JSON_STR}\n```'),
        ]
    )
    def test_required_keys_pick_the_answer_over_an_earlier_object(self, _name, text):
        # An agent turn holds tool calls and error envelopes before its answer, and the first
        # object used to win — the caller then failed schema validation on an error-shaped dict.
        assert extract_json_from_text(text, label="test", required_keys={"answer"}) == EXPECTED

    def test_required_keys_absent_everywhere_keep_the_first_object(self):
        text = f'{{"type": "error", "message": "query failed"}}\n{JSON_STR}'
        assert extract_json_from_text(text, label="test", required_keys={"repository"}) == {
            "type": "error",
            "message": "query failed",
        }
