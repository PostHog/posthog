from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.scout_harness.tools.report_quality import apply_report_quality_checks


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
        result = apply_report_quality_checks(title="Checkout p99 regressed", summary=summary, can_edit_report=True)
        assert result.summary == expected
        assert [hint.check_id for hint in result.hints] == check_ids

    @parameterized.expand(
        [
            ("fix(checkout): handle empty cart", True, ["pr_style_title"]),
            ("feat!: new flow", True, ["pr_style_title"]),
            ("feat!: new flow", False, ["pr_style_title"]),
            ("Fix rate for checkout dropped after 4.2", True, []),
        ]
    )
    def test_pr_style_title_is_a_hint_only(self, title: str, can_edit_report: bool, check_ids: list[str]) -> None:
        result = apply_report_quality_checks(title=title, summary=None, can_edit_report=can_edit_report)
        assert result.title == title
        assert [hint.check_id for hint in result.hints] == check_ids

    @parameterized.expand([(True, True), (False, False)])
    def test_pr_style_title_names_edit_report_only_to_a_caller_that_can_edit(
        self, can_edit_report: bool, tells_to_edit: bool
    ) -> None:
        result = apply_report_quality_checks(
            title="fix(checkout): handle empty cart", summary=None, can_edit_report=can_edit_report
        )
        (hint,) = result.hints
        assert ("Rewrite it with edit_report" in hint.message) is tells_to_edit
        assert ("You cannot call edit_report" in hint.message) is not tells_to_edit
