from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.flow_attach import VisitCounts, find_attached_issues
from products.error_tracking.backend.logic.recommendations.flow_drop import find_drop_hours
from products.error_tracking.backend.logic.recommendations.page_flows import (
    EvaluationWindow,
    Flow,
    StepCounts,
    is_surge,
    merge_drop_hours,
    pick_flows,
)

TEAM_ID = 1
HOUR = datetime(2026, 1, 15, 9, tzinfo=UTC)
WINDOW = EvaluationWindow(first_hour=HOUR - timedelta(hours=6), last_hour=HOUR)


def _hours(baseline: tuple[int, int], baseline_days: int, hour: datetime, current: tuple[int, int]) -> dict:
    hours = {hour - timedelta(days=days): StepCounts(reached=baseline) for days in range(1, baseline_days + 1)}
    hours[hour] = StepCounts(reached=current)
    return hours


class TestPickFlows(SimpleTestCase):
    @parameterized.expand(
        [
            # name, sessions on the start page, sessions that went directly to the next page
            ("step_some_people_take", 300, 120, True),
            ("redirect_almost_everyone_takes", 300, 290, False),
            ("transition_almost_nobody_takes", 1000, 45, False),
            ("too_few_transition_sessions", 300, 39, False),
            ("start_page_too_quiet", 99, 50, False),
        ]
    )
    def test_picks_steps_that_only_some_people_complete(
        self, _name: str, page_sessions: int, transition_sessions: int, picked: bool
    ) -> None:
        rows = [
            (TEAM_ID, "page", "/login", "", page_sessions),
            (TEAM_ID, "transition", "/login", "/home", transition_sessions),
        ]

        self.assertEqual(
            pick_flows(rows).get(TEAM_ID, []), [Flow(from_path="/login", to_path="/home")] if picked else []
        )

    def test_keeps_two_flows_per_page_and_skips_reverse_duplicates(self) -> None:
        rows = [
            (TEAM_ID, "page", "/login", "", 1000),
            (TEAM_ID, "page", "/home", "", 1000),
            (TEAM_ID, "transition", "/login", "/home", 500),
            (TEAM_ID, "transition", "/login", "/settings", 300),
            (TEAM_ID, "transition", "/login", "/billing", 200),
            (TEAM_ID, "transition", "/home", "/login", 400),
            (TEAM_ID, "transition", "/home", "/settings", 100),
        ]

        self.assertEqual(
            pick_flows(rows)[TEAM_ID],
            [
                Flow(from_path="/login", to_path="/home"),
                Flow(from_path="/login", to_path="/settings"),
                Flow(from_path="/home", to_path="/settings"),
            ],
        )


class TestFindDropHours(SimpleTestCase):
    @parameterized.expand(
        [
            # name, baseline (starts, finishes) per day, baseline days, current (starts, finishes), hour, dropped
            ("rate_collapses", (60, 33), 4, (250, 30), HOUR, True),
            ("too_few_starts", (60, 33), 4, (199, 10), HOUR, False),
            ("too_few_baseline_days", (60, 33), 3, (250, 30), HOUR, False),
            ("baseline_days_too_quiet", (29, 16), 7, (250, 30), HOUR, False),
            ("drop_under_eight_points", (60, 12), 4, (250, 33), HOUR, False),
            ("rate_above_three_quarters_of_usual", (60, 33), 4, (250, 110), HOUR, False),
            ("hour_before_window", (60, 33), 4, (250, 30), WINDOW.first_hour - timedelta(hours=1), False),
            ("hour_still_settling", (60, 33), 4, (250, 30), HOUR + timedelta(hours=1), False),
        ]
    )
    def test_flags_hours_far_below_the_same_hour_on_previous_days(
        self,
        _name: str,
        baseline: tuple[int, int],
        baseline_days: int,
        current: tuple[int, int],
        hour: datetime,
        dropped: bool,
    ) -> None:
        self.assertEqual(
            find_drop_hours(_hours(baseline, baseline_days, hour, current), WINDOW), [hour] if dropped else []
        )

    @parameterized.expand(
        [
            # name, now, the last hour a run evaluates
            (
                "just_before_the_hour_settles",
                datetime(2026, 1, 15, 12, 29, tzinfo=UTC),
                datetime(2026, 1, 15, 10, tzinfo=UTC),
            ),
            ("once_the_hour_settles", datetime(2026, 1, 15, 12, 30, tzinfo=UTC), datetime(2026, 1, 15, 11, tzinfo=UTC)),
        ]
    )
    def test_evaluates_only_hours_whose_visits_had_time_to_finish(
        self, _name: str, now: datetime, last_hour: datetime
    ) -> None:
        window = EvaluationWindow.ending_before(now)

        self.assertEqual((window.first_hour, window.last_hour), (last_hour - timedelta(hours=23), last_hour))

    def test_merges_consecutive_drop_hours_into_one_incident(self) -> None:
        later = HOUR + timedelta(hours=3)

        self.assertEqual(
            merge_drop_hours([later, HOUR + timedelta(hours=1), HOUR]),
            [[HOUR, HOUR + timedelta(hours=1)], [later]],
        )

    @parameterized.expand(
        [
            # name, each incident hour's (starts, finishes) against a usual 60 starts and 33 finishes
            ("extra_traffic_with_usual_finishes", [(420, 33)], True),
            ("extra_traffic_with_fewer_finishes", [(420, 20)], False),
            ("less_than_three_times_the_traffic", [(170, 33)], False),
            # The busiest hour decides: a quiet broken hour next to a surge hour is still a surge.
            ("busiest_hour_of_several_is_a_surge", [(200, 5), (420, 33)], True),
            ("busiest_hour_of_several_lost_finishes", [(200, 40), (420, 10)], False),
        ]
    )
    def test_treats_extra_traffic_with_usual_finishes_as_a_surge(
        self, _name: str, incident: list[tuple[int, int]], surge: bool
    ) -> None:
        drop = [HOUR + timedelta(hours=offset) for offset in range(len(incident))]
        hours = {hour - timedelta(days=days): StepCounts(reached=(60, 33)) for hour in drop for days in range(1, 5)}
        hours.update({hour: StepCounts(reached=(starts, finishes)) for hour, (starts, finishes) in zip(drop, incident)})

        self.assertEqual(is_surge(hours, drop), surge)


class TestFindAttachedIssues(SimpleTestCase):
    @parameterized.expand(
        [
            # name, all visits by days before the incident, the issue's visits by day, attached
            ("exposed_visits_rarely_finish", {0: (1000, 120), 1: (800, 96)}, {0: (300, 9)}, True),
            ("too_few_exposed_visits", {0: (1000, 120), 1: (800, 96)}, {0: (19, 0)}, False),
            ("too_few_unexposed_visits", {0: (1000, 120)}, {0: (981, 20)}, False),
            ("exposed_finish_more_than_half_as_often", {0: (10000, 5000)}, {0: (2000, 600)}, False),
            ("difference_under_four_standard_errors", {0: (1000, 120), 1: (800, 96)}, {0: (20, 0)}, False),
            # The issue's gap the day before was 12 points (15% against 3%), so a 13-point gap today is usual.
            ("gap_like_the_issues_usual_gap", {0: (1000, 120), 1: (800, 96)}, {0: (300, 9), 1: (200, 6)}, False),
            # The day before, the issue's visits finished more often than the rest, so today's gap is 17 points wider.
            ("gap_far_wider_than_usual", {0: (1000, 120), 1: (800, 96)}, {0: (300, 9), 1: (200, 30)}, True),
            # With 19 usual exposed visits the usual gap is too thin to judge, so it does not apply.
            ("too_few_usual_exposed_visits", {0: (1000, 120), 1: (800, 96)}, {0: (300, 9), 1: (19, 0)}, True),
        ]
    )
    def test_attaches_issues_whose_visits_fail_far_more_than_other_visits(
        self,
        _name: str,
        all_visits: dict[int, tuple[int, int]],
        issue_visits: dict[int, tuple[int, int]],
        attached: bool,
    ) -> None:
        counts = {
            key: {days: VisitCounts(visits=visits, finishes=finishes) for days, (visits, finishes) in by_day.items()}
            for key, by_day in (("", all_visits), ("issue", issue_visits))
        }

        self.assertEqual([issue.issue_id for issue in find_attached_issues(counts)], ["issue"] if attached else [])
