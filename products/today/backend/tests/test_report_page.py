from dataclasses import replace

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.facade import api as signals
from products.today.backend.logic.prose import concise_text
from products.today.backend.logic.report_page import figure_marks, report_page
from products.today.backend.tests.factories import AGREEING, SameAnswerJev, page_source, signal

SOLUTION_PR = "Reuse draft https://github.com/example/web/pull/9."


class TestReportPage(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "keeps a title with its name",
                "Ask Dr. Smith to review this change. Then ship it.",
                40,
                "Ask Dr. Smith to review this change.",
            ),
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
            (
                "a link and a different bare reference",
                "Merged in https://github.com/example/web/pull/7, and PR #8 follows.",
                None,
                None,
            ),
        ]
    )
    def test_names_the_pull_request(self, _name: str, summary: str, solution: str | None, expected: int | None) -> None:
        pull_request = report_page(page_source(summary=summary, solution=solution)).named_pull_request
        assert (pull_request.number if pull_request else None) == expected

    @parameterized.expand(
        [
            ("a solution", page_source(solution="Keep the token.", action_prompts=["Fix it"]), "Keep the token."),
            ("the first prompt when work can start", page_source(action_prompts=["Fix it", "Test it"]), "Fix it."),
            ("nothing without a solution or a prompt", page_source(), ""),
        ]
    )
    def test_proposes(self, _name: str, source: signals.ReportPageSource, expected: str) -> None:
        assert report_page(source).proposal == expected

    @parameterized.expand(
        [
            ("a measurement", "212 shoppers could not pay.", "212 shoppers could not pay."),
            ("no number", "Shoppers could not pay.", ""),
            ("only digits in code", "`checkout/address_v2.ts` drops it.", ""),
            (
                "a measurement beside a code path",
                "`checkout/address.ts` fails for 12 users.",
                "`checkout/address.ts` fails for 12 users.",
            ),
        ]
    )
    def test_keeps_only_a_measured_impact(self, _name: str, impact: str, expected: str) -> None:
        assert report_page(page_source(impact=impact)).impact_sentence == expected

    def test_sees_a_bare_reference_without_a_repository(self) -> None:
        page = report_page(replace(page_source(solution="PR #5 already fixes this."), repo_slug=None))
        assert (page.named_pull_request, page.solution_names_pull_request) == (None, True)

    def test_marks_numbers_in_prose_but_not_in_code(self) -> None:
        source = signal(content="The export failed for 212 users.")
        page = replace(
            page_source(),
            sections=signals.ReportSections(lead="`limit=212` stops 212 users.", impact=None, solution=None),
            signals=[source],
        )
        marks = figure_marks(page, [], SameAnswerJev(AGREEING))
        assert [(mark.start, mark.figure) for mark in marks] == [(16, "212")]
