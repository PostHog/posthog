from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.report_prompts import MAX_SUGGESTED_PROMPT_LENGTH, MAX_SUGGESTED_PROMPTS
from products.signals.backend.scout_harness.tools.report_quality import (
    apply_report_quality_checks,
    repair_suggested_prompts,
)

_TOO_LONG = "x" * (MAX_SUGGESTED_PROMPT_LENGTH + 1)


class TestReportQualityChecks(SimpleTestCase):
    @parameterized.expand(
        [
            ("over_escaped_newlines", "a\\n\\nb\\r\\nc", "a\n\nb\nc", ["literal_newline_escapes"]),
            ("real_newlines_keep_a_code_sample", 'a\nUse `print("\\n")`', 'a\nUse `print("\\n")`', []),
            ("only_escaped_backticks", "Run \\`ls\\`", "Run `ls`", ["escaped_backticks"]),
            ("mixed_backticks_kept", "Use `a` and a literal \\` here", "Use `a` and a literal \\` here", []),
            ("clean_text", "Line one\nLine two", "Line one\nLine two", []),
        ]
    )
    def test_summary_repairs(self, _name: str, summary: str, expected: str, check_ids: list[str]) -> None:
        result = apply_report_quality_checks(title="Checkout p99 regressed", summary=summary)
        assert result.summary == expected
        assert [hint.check_id for hint in result.hints] == check_ids

    @parameterized.expand(
        [
            ("fix(checkout): handle empty cart", ["pr_style_title"]),
            ("feat!: new flow", ["pr_style_title"]),
            ("Fix rate for checkout dropped after 4.2", []),
        ]
    )
    def test_pr_style_title_is_a_hint_only(self, title: str, check_ids: list[str]) -> None:
        result = apply_report_quality_checks(title=title, summary=None)
        assert result.title == title
        assert [hint.check_id for hint in result.hints] == check_ids

    @parameterized.expand(
        [
            ("omitted", None, None, []),
            ("cleared", [], [], []),
            ("inside_the_bounds", ["Which teams?", "Since when?"], ["Which teams?", "Since when?"], []),
            ("blank_only_still_clears", ["  "], [], []),
            ("one_too_long", ["Which teams?", _TOO_LONG], ["Which teams?"], ["suggested_prompt_too_long"]),
            ("only_too_long_keeps_the_stored_set", [_TOO_LONG], None, ["suggested_prompt_too_long"]),
            ("duplicate", ["Which teams?", " Which teams? "], ["Which teams?"], ["duplicate_suggested_prompt"]),
            (
                "past_the_cap",
                [f"Question {i}?" for i in range(MAX_SUGGESTED_PROMPTS + 2)],
                [f"Question {i}?" for i in range(MAX_SUGGESTED_PROMPTS)],
                ["too_many_suggested_prompts"],
            ),
            (
                "the_cap_counts_after_the_other_bounds",
                [_TOO_LONG, "A?", "A?", "B?", "C?"],
                ["A?", "B?", "C?"],
                ["suggested_prompt_too_long", "duplicate_suggested_prompt"],
            ),
        ]
    )
    def test_suggested_prompts_past_a_bound_are_left_out(
        self, _name: str, prompts: list[str] | None, expected: list[str] | None, check_ids: list[str]
    ) -> None:
        result = repair_suggested_prompts(prompts)
        assert result.prompts == expected
        assert [hint.check_id for hint in result.hints] == check_ids
