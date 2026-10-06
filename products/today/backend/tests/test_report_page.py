from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.facade import api as signals
from products.today.backend.logic.report_page import concise_text, report_page

SOLUTION_PR = "Reuse draft https://github.com/example/web/pull/9."


def page_source(
    *,
    summary: str = "",
    solution: str | None = None,
    impact: str | None = None,
    status: str = "ready",
    has_pull_requests: bool = False,
    suggested_prompts: list[str] | None = None,
) -> signals.ReportPageSource:
    return signals.ReportPageSource(
        summary=summary,
        sections=signals.ReportSections(lead="Lead.", impact=impact, solution=solution),
        status=status,
        actionability="immediately_actionable",
        already_addressed=False,
        has_pull_requests=has_pull_requests,
        suggested_prompts=suggested_prompts or [],
        repo_slug="example/web",
        signals=[],
    )


class TestReportPage(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "stops before the limit",
                "First sentence is short. Second sentence is also short. Third one.",
                50,
                "First sentence is short.",
            ),
            (
                "keeps one long sentence",
                "One long sentence that runs past the limit on its own.",
                10,
                "One long sentence that runs past the limit on its own.",
            ),
            (
                "reads list items as sentences",
                "- Reproduce the bug\n- Trace the state",
                60,
                "Reproduce the bug. Trace the state.",
            ),
            (
                "counts a link by the text it shows",
                "Merged in [#12](https://github.com/example/web/pull/12). Land [#13](https://github.com/example/web/pull/13) next.",
                40,
                "Merged in [#12](https://github.com/example/web/pull/12). Land [#13](https://github.com/example/web/pull/13) next.",
            ),
            (
                "closes a bold span it cuts",
                "**The fix is safe. It ships today.** Then measure.",
                20,
                "**The fix is safe.**",
            ),
            (
                "ends a sentence inside bold",
                "That covers the ask. **One message is still open.** Then add a deletion type for events.",
                60,
                "That covers the ask. **One message is still open.**",
            ),
            (
                "keeps a period inside code",
                'Match quotes with `(?:[^"\\\\]|\\\\.)*`. Then ship it.',
                40,
                'Match quotes with `(?:[^"\\\\]|\\\\.)*`.',
            ),
        ]
    )
    def test_keeps_text_concise(self, _name: str, markdown: str, max_chars: int, expected: str) -> None:
        assert concise_text(markdown, max_chars) == expected

    @parameterized.expand(
        [
            ("one pull request", "Open PR https://github.com/example/web/pull/7 covers it.", None, 7),
            (
                "several pull requests",
                "Merged in https://github.com/example/web/pull/7, review https://github.com/example/web/pull/8.",
                None,
                None,
            ),
            (
                "several pull requests, one named by the solution",
                "Merged in https://github.com/example/web/pull/7. Reuse https://github.com/example/web/pull/9.",
                SOLUTION_PR,
                9,
            ),
            ("a bare reference in the repository", "PR #5 already fixes this.", None, 5),
        ]
    )
    def test_names_the_in_flight_pull_request(
        self, _name: str, summary: str, solution: str | None, expected: int | None
    ) -> None:
        pull_request = report_page(page_source(summary=summary, solution=solution)).in_flight_pull_request
        assert (pull_request.number if pull_request else None) == expected

    @parameterized.expand(
        [
            ("a solution", page_source(solution="Keep the token.", suggested_prompts=["Fix it"]), "Keep the token."),
            ("the first prompt when work can start", page_source(suggested_prompts=["Fix it", "Test it"]), "Fix it."),
            (
                "no prompt when a pull request exists",
                page_source(has_pull_requests=True, suggested_prompts=["Fix it"]),
                "",
            ),
            ("no prompt once resolved", page_source(status="resolved", suggested_prompts=["Fix it"]), ""),
        ]
    )
    def test_proposes(self, _name: str, source: signals.ReportPageSource, expected: str) -> None:
        assert report_page(source).proposal == expected

    @parameterized.expand(
        [
            ("a measurement", "212 shoppers could not pay.", "212 shoppers could not pay."),
            ("no number", "Shoppers could not pay.", ""),
            ("a code path", "Line 42 of `checkout/address.ts` drops it.", ""),
        ]
    )
    def test_keeps_only_a_measured_impact(self, _name: str, impact: str, expected: str) -> None:
        assert report_page(page_source(impact=impact)).impact_sentence == expected
