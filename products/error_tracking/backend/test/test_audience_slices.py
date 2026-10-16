from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.audience_slices import (
    BaselineRow,
    SliceRow,
    evaluable_teams,
    find_audience_slices,
)

TEAM_ID = 1
ISSUE_ID = "issue-1"


def _slice(
    issue_id: str, dimension: str, value: str, sessions: int, issue_sessions: int, pageview_sessions: int
) -> SliceRow:
    return SliceRow(
        team_id=TEAM_ID,
        issue_id=issue_id,
        dimension=dimension,
        value=value,
        sessions=sessions,
        issue_sessions=issue_sessions,
        pageview_sessions=pageview_sessions,
    )


def _baseline(dimension: str, value: str, sessions: int) -> BaselineRow:
    return BaselineRow(team_id=TEAM_ID, dimension=dimension, value=value, sessions=sessions)


class TestFindAudienceSlices(SimpleTestCase):
    @parameterized.expand(
        [
            # name, dimension, value, value sessions, issue sessions, sessions with a pageview, baseline value sessions
            ("concentrated_browser", "browser", "Firefox", 95, 100, 90, 50, True),
            # A value the pageview traffic lacks, such as bots that send no pageviews, still gets a floor share.
            ("value_missing_from_pageview_traffic", "browser", "Firefox", 95, 100, 90, 0, True),
            ("lift_below_three", "browser", "Firefox", 60, 100, 90, 300, False),
            ("too_few_issue_sessions", "browser", "Firefox", 50, 50, 50, 50, False),
            ("issue_mostly_without_pageviews", "browser", "Firefox", 95, 100, 30, 50, False),
            ("blank_value", "browser", " ", 95, 100, 90, 50, False),
            ("unknown_dimension", "country", "US", 95, 100, 90, 50, False),
        ]
    )
    def test_flags_only_concentrated_values(
        self,
        _name: str,
        dimension: str,
        value: str,
        sessions: int,
        issue_sessions: int,
        pageview_sessions: int,
        baseline_sessions: int,
        expected: bool,
    ) -> None:
        issue_rows = [_slice(ISSUE_ID, dimension, value, sessions, issue_sessions, pageview_sessions)]
        baseline = [_baseline("__total", "", 1000), _baseline(dimension, value, baseline_sessions)]

        result = find_audience_slices(issue_rows, baseline)

        self.assertEqual(bool(result.get(TEAM_ID)), expected)

    def test_keeps_the_three_strongest_slices_and_orders_issues_by_lift(self) -> None:
        issue_rows = [
            _slice("weak", "browser", "Firefox", 95, 100, 100),
            _slice("strong", "browser", "Firefox", 60, 100, 100),
            _slice("strong", "os", "Linux", 99, 100, 100),
            _slice("strong", "device_type", "Desktop", 99, 100, 100),
            _slice("strong", "user_agent", "bot", 99, 100, 100),
        ]
        baseline = [
            _baseline("__total", "", 1000),
            _baseline("browser", "Firefox", 100),
            _baseline("os", "Linux", 5),
            _baseline("device_type", "Desktop", 300),
            _baseline("user_agent", "bot", 3),
        ]

        result = find_audience_slices(issue_rows, baseline)

        self.assertEqual([issue["id"] for issue in result[TEAM_ID]], ["strong", "weak"])
        self.assertEqual(
            [(s["dimension"], s["value"]) for s in result[TEAM_ID][0]["slices"]],
            [("user_agent", "bot"), ("os", "Linux"), ("browser", "Firefox")],
        )

    @parameterized.expand([("enough_pageview_sessions", 100, True), ("too_few_pageview_sessions", 99, False)])
    def test_evaluable_only_with_enough_pageview_traffic(self, _name: str, total: int, expected: bool) -> None:
        self.assertEqual(evaluable_teams([_baseline("__total", "", total)]) == {TEAM_ID}, expected)
