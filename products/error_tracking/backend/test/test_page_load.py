from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.page_load import (
    Measure,
    PageLoadRow,
    evaluable_teams,
    find_repeated_findings,
)

TEAM_ID = 1
NO_COUNTS = Measure(pageviews=0, observed=0, expected=0.0)


def _row(label: str, day: int, quick: tuple[int, int, float], team_id: int = TEAM_ID) -> PageLoadRow:
    pageviews, observed, expected = quick
    return PageLoadRow(
        team_id=team_id,
        day=day,
        label=label,
        quick=Measure(pageviews=pageviews, observed=observed, expected=expected),
        returned=NO_COUNTS,
        lost=NO_COUNTS,
    )


class TestFindRepeatedFindings(SimpleTestCase):
    @parameterized.expand(
        [
            # name, days the issue has a row, its (pageviews, observed, expected), fake rows, excluded issues
            ("far_above_expected_on_both_days", (0, 1), (120, 92, 29.0), [], set(), True),
            ("only_on_the_most_recent_day", (0,), (120, 92, 29.0), [], set(), False),
            ("too_few_pageviews", (0, 1), (40, 35, 9.0), [], set(), False),
            ("lift_below_one_and_a_half", (0, 1), (1000, 330, 250.0), [], set(), False),
            # Twice the expected rate, but 8 of 50 against 4 expected is about 2 standard errors.
            ("difference_under_four_standard_errors", (0, 1), (50, 8, 4.0), [], set(), False),
            (
                "fake_shows_the_comparison_is_biased",
                (0, 1),
                (120, 92, 29.0),
                [("__fake_10", (2000, 1500, 500.0))],
                set(),
                False,
            ),
            ("small_fake_is_ignored", (0, 1), (120, 92, 29.0), [("__fake_3", (100, 75, 25.0))], set(), True),
            ("fires_as_people_leave", (0, 1), (120, 92, 29.0), [], {"issue"}, False),
        ]
    )
    def test_flags_issues_far_above_the_comparison_on_two_days(
        self,
        _name: str,
        days: tuple[int, ...],
        counts: tuple[int, int, float],
        fakes: list[tuple[str, tuple[int, int, float]]],
        excluded: set[str],
        flagged: bool,
    ) -> None:
        rows = [_row("issue", day, counts) for day in days]
        rows += [_row(label, day, fake) for label, fake in fakes for day in (0, 1)]

        findings = find_repeated_findings(rows, lambda row: row.quick, {TEAM_ID: excluded}).get(TEAM_ID, [])

        self.assertEqual([finding.issue_id for finding in findings], ["issue"] if flagged else [])

    def test_only_teams_with_comparison_pageviews_on_the_most_recent_day_are_evaluable(self) -> None:
        rows = [
            _row("__control", 0, (300, 60, 60.0), team_id=1),
            _row("__control", 0, (0, 0, 0.0), team_id=2),
            _row("__control", 1, (300, 60, 60.0), team_id=3),
            _row("issue", 0, (80, 70, 20.0), team_id=4),
        ]

        self.assertEqual(evaluable_teams(rows, lambda row: row.quick), {1})
