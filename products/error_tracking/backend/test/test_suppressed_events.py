from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.recommendations.suppressed_events import (
    COMPARISON_GROUP,
    ISSUE_GROUP,
    TOTAL,
    evaluable_teams,
    find_suppressed_events,
)

TEAM_ID = 1
TARGETS = [(TEAM_ID, "issue", "app.example.com/connect", 80)]


def _rows(
    issue_sessions: int, comparison_sessions: int, events: dict[str, tuple[int, int]]
) -> list[tuple[int, str, str, str, int]]:
    rows = [
        (TEAM_ID, "issue", ISSUE_GROUP, TOTAL, issue_sessions),
        (TEAM_ID, "issue", COMPARISON_GROUP, TOTAL, comparison_sessions),
    ]
    for event, (in_issue, in_comparison) in events.items():
        rows += [
            (TEAM_ID, "issue", ISSUE_GROUP, event, in_issue),
            (TEAM_ID, "issue", COMPARISON_GROUP, event, in_comparison),
        ]
    return rows


class TestSuppressedEvents(SimpleTestCase):
    @parameterized.expand(
        [
            # name, issue sessions, comparison sessions, event sessions in the issue group, in the comparison group
            ("event_stops_after_the_error", 80, 260, 5, 141, True),
            ("too_few_issue_sessions", 59, 260, 0, 141, False),
            ("too_few_comparison_sessions", 80, 199, 5, 108, False),
            ("drop_smaller_than_half", 80, 260, 40, 141, False),
            ("event_too_rare", 80, 260, 0, 6, False),
            ("drop_not_significant", 60, 200, 0, 10, False),
        ]
    )
    def test_flags_events_people_stop_sending_after_the_error(
        self,
        _name: str,
        issue_sessions: int,
        comparison_sessions: int,
        in_issue: int,
        in_comparison: int,
        flagged: bool,
    ) -> None:
        rows = _rows(issue_sessions, comparison_sessions, {"integration_connected": (in_issue, in_comparison)})

        issues = find_suppressed_events(TARGETS, rows).get(TEAM_ID, [])

        self.assertEqual([issue["id"] for issue in issues], ["issue"] if flagged else [])

    def test_keeps_the_three_largest_drops(self) -> None:
        rows = _rows(80, 260, {"a": (0, 75), "b": (0, 200), "c": (0, 120), "d": (0, 70), "e": (20, 80)})

        issues = find_suppressed_events(TARGETS, rows)[TEAM_ID]

        self.assertEqual([event["event"] for event in issues[0]["events"]], ["b", "c", "a"])

    @parameterized.expand([("custom_event", "signed_up", True), ("only_posthog_events", "$web_vitals_lcp", False)])
    def test_evaluable_only_with_custom_events(self, _name: str, event: str, evaluable: bool) -> None:
        rows = _rows(80, 260, {event: (1, 1)})

        self.assertEqual(evaluable_teams(TARGETS, rows), {TEAM_ID} if evaluable else set())
