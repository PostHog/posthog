import math

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.inflated_counts import RepetitionRow, find_inflated_counts

TEAM_ID = 1
NO_TIMER = math.nan


class TestFindInflatedCounts(SimpleTestCase):
    @parameterized.expand(
        [
            # name, sessions, occurrences, top session, heavy sessions, repeating, on a timer, timer gap ms
            ("one_session_dominates", 50, 200, 100, 100, 1, 0, NO_TIMER, ["top_session", "heavy_sessions"]),
            ("heavy_sessions_without_one_top_session", 50, 1000, 100, 600, 10, 0, NO_TIMER, ["heavy_sessions"]),
            ("repeats_on_a_timer", 60, 300, 30, 0, 20, 10, 60000.0, ["timer"]),
            ("too_few_repeating_sessions_for_a_timer", 60, 300, 30, 0, 9, 9, 60000.0, []),
            ("spread_across_sessions", 100, 150, 3, 0, 0, 0, NO_TIMER, []),
            ("too_few_sessions", 39, 400, 300, 300, 1, 0, NO_TIMER, []),
        ]
    )
    def test_flags_issues_whose_count_comes_from_a_few_sessions(
        self,
        _name: str,
        sessions: int,
        occurrences: int,
        top_session: int,
        heavy_sessions: int,
        repeating: int,
        timer_sessions: int,
        timer_gap_ms: float,
        expected_reasons: list[str],
    ) -> None:
        rows = [
            RepetitionRow(
                team_id=TEAM_ID,
                issue_id="issue",
                sessions=sessions,
                occurrences=occurrences,
                top_session_occurrences=top_session,
                heavy_session_occurrences=heavy_sessions,
                repeating_sessions=repeating,
                timer_sessions=timer_sessions,
                timer_gap_ms=timer_gap_ms,
            )
        ]

        issues = find_inflated_counts(rows).get(TEAM_ID, [])

        self.assertEqual([issue["reasons"] for issue in issues], [expected_reasons] if expected_reasons else [])
        if "timer" in expected_reasons:
            self.assertEqual(issues[0]["timer_interval_seconds"], 60)
