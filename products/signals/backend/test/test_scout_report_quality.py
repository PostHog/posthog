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
