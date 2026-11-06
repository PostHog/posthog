from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.report_sections import ReportSections, report_sections


class TestReportSections(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "markdown headings",
                "Lead sentence.\n\n## Problem\n\nBroken.\n\n## Impact\n\n**12 people** hit it. [Failures](chart:failures)\n\n## Solution\n\nFix the key.",
                ReportSections(lead="Lead sentence.", impact="**12 people** hit it.", solution="Fix the key."),
            ),
            (
                "an aliased solution heading",
                "Lead.\n\n## The fix\n\nKeep the token in a cookie.",
                ReportSections(lead="Lead.", impact=None, solution="Keep the token in a cookie."),
            ),
            (
                "a heading inside a code block",
                "Lead.\n\n## Solution\n\nRun this:\n\n```\n# Impact\nmigrate\n```",
                ReportSections(lead="Lead.", impact=None, solution="Run this:\n\n```\n# Impact\nmigrate\n```"),
            ),
            (
                "bold paragraph headings",
                "Lead sentence.\n\n**Evidence**\n\n- A finding.\n\n**Recommended next step**\n\n- Inspect the [rate](chart:rate) path.",
                ReportSections(lead="Lead sentence.", impact=None, solution="- Inspect the rate path."),
            ),
            (
                "a bold lead sentence",
                "**One-page checkout won. It is safe to ship.**\n\nThe shorter checkout completed more often.",
                ReportSections(lead="**One-page checkout won. It is safe to ship.**", impact=None, solution=None),
            ),
            (
                "a summary that opens with its problem heading",
                "## Problem\n\nCheckout drops the coupon.\n\n## Solution\n\nKeep it in the cart.",
                ReportSections(lead="Checkout drops the coupon.", impact=None, solution="Keep it in the cart."),
            ),
            (
                "a bold label inside a fenced example",
                "Lead.\n\n**Fix**\n\nRun this:\n\n```\n**Solution**\nmigrate\n```",
                ReportSections(lead="Lead.", impact=None, solution="Run this:\n\n```\n**Solution**\nmigrate\n```"),
            ),
            ("no summary", None, ReportSections(lead="", impact=None, solution=None)),
        ]
    )
    def test_report_sections(self, _name: str, summary: str | None, expected: ReportSections) -> None:
        assert report_sections(summary) == expected
