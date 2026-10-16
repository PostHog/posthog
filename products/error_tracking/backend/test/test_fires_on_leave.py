from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.fires_on_leave import (
    BASELINE_CLICK,
    BASELINE_PAGEVIEW,
    PAGELEAVE_SESSIONS,
    LeaveRow,
    baseline_leave_shares,
    evaluable_teams,
    find_fires_on_leave,
)

TEAM_ID = 1


def _row(label: str, sessions: int, leave: int, team_id: int = TEAM_ID) -> LeaveRow:
    return LeaveRow(
        team_id=team_id,
        label=label,
        sessions=sessions,
        leave_sessions=leave,
        navigation_sessions=0,
        action_sessions=0,
        background_sessions=0,
    )


class TestFiresOnLeave(SimpleTestCase):
    @parameterized.expand(
        [
            # name, issue sessions, issue sessions next to a pageleave, baseline moments, baseline moments next to one
            ("leaves_far_more_than_random_moments", 70, 57, 100, 2, True),
            ("too_few_sessions", 39, 35, 100, 2, False),
            ("below_twice_the_baseline", 100, 50, 100, 30, False),
            ("below_ten_percent", 50, 4, 100, 1, False),
            ("too_few_random_moments_for_a_baseline", 70, 57, 29, 0, False),
        ]
    )
    def test_flags_issues_that_fire_as_people_leave(
        self,
        _name: str,
        sessions: int,
        leave: int,
        baseline_moments: int,
        baseline_leave: int,
        flagged: bool,
    ) -> None:
        rows = [_row("issue", sessions, leave), _row(BASELINE_CLICK, baseline_moments, baseline_leave)]

        issues = find_fires_on_leave(rows, baseline_leave_shares(rows)).get(TEAM_ID, [])

        self.assertEqual([issue["id"] for issue in issues], ["issue"] if flagged else [])

    def test_baseline_averages_the_random_moments_that_have_enough_samples(self) -> None:
        rows = [_row(BASELINE_CLICK, 100, 10), _row(BASELINE_PAGEVIEW, 50, 20), _row(BASELINE_CLICK, 29, 29, team_id=2)]

        self.assertEqual(baseline_leave_shares(rows), {TEAM_ID: 0.25})

    def test_only_teams_that_send_pageleave_events_are_evaluable(self) -> None:
        rows = [
            _row(BASELINE_CLICK, 100, 1),
            _row(PAGELEAVE_SESSIONS, 12, 0),
            _row(BASELINE_CLICK, 100, 0, team_id=2),
        ]

        self.assertEqual(evaluable_teams(rows, baseline_leave_shares(rows)), {TEAM_ID})
