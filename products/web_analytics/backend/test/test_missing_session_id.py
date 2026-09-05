import uuid
import datetime as dt

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue
from posthog.models.utils import uuid7

from products.web_analytics.backend.temporal.health_checks.missing_session_id import MissingSessionIdCheck

MODULE = "products.web_analytics.backend.temporal.health_checks.missing_session_id"


@pytest.mark.parametrize(
    "mock_rows, expected_teams",
    [
        ([], set()),
        ([(42, 20_000, 6_000, 6_000, 5_000, 1_500)], {42}),
        ([(1, 50_000, 40_000, 40_000, 10_000, 8_000), (3, 12_000, 800, 500, 3_000, 200)], {1, 3}),
    ],
    ids=["all_healthy", "single_team_unusable_session_ids", "multiple_teams_flagged"],
)
@patch(f"{MODULE}.execute_clickhouse_health_team_query")
def test_detect_missing_session_id(mock_query: MagicMock, mock_rows: list, expected_teams: set) -> None:
    mock_query.return_value = mock_rows

    result = MissingSessionIdCheck().detect([1, 2, 3, 42])

    assert set(result.keys()) == expected_teams
    for team_id in expected_teams:
        issues = result[team_id]
        assert len(issues) == 1
        assert issues[0].severity == HealthIssue.Severity.WARNING
        assert "$session_id" in issues[0].payload["reason"]


@patch(f"{MODULE}.execute_clickhouse_health_team_query")
def test_reason_reports_share_and_splits_the_causes(mock_query: MagicMock) -> None:
    mock_query.return_value = [(7, 20_000, 5_000, 3_000, 5_000, 1_250)]

    reason = MissingSessionIdCheck().detect([7])[7][0].payload["reason"]

    assert "25.0%" in reason
    assert "3000 absent or not a UUID, 2000 not a UUIDv7" in reason


class TestMissingSessionIdQuery(ClickhouseTestMixin, BaseTest):
    def _create_pageviews(self, session_ids: list[str | None], days_ago: int = 1) -> None:
        timestamp = dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)
        for index, session_id in enumerate(session_ids):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user-{index}",
                timestamp=timestamp,
                properties={} if session_id is None else {"$session_id": session_id},
            )
        flush_persons_and_events()

    def _flagged(self) -> bool:
        # Small threshold and floor keep the row count down. The production values only decide
        # sensitivity, while the conditions under test are which events count as unusable, whether the
        # floor counts unusable events or total events, and whether the recent window clears the issue.
        with (
            patch(f"{MODULE}.MISSING_SESSION_ID_THRESHOLD", 0.5),
            patch(f"{MODULE}.MISSING_SESSION_ID_MIN_UNUSABLE", 2),
        ):
            return self.team.id in MissingSessionIdCheck().detect([self.team.id])

    @parameterized.expand(
        [
            ("uuidv7_ids_are_usable", [str(uuid7()), str(uuid7())], False),
            ("no_session_id_property", [None, None], True),
            ("empty_session_id", ["", ""], True),
            ("session_id_is_not_a_uuid", ["not-a-uuid", "not-a-uuid"], True),
            ("uuidv4_ids_never_reach_a_session", [str(uuid.uuid4()), str(uuid.uuid4())], True),
            ("below_the_unusable_floor", [None], False),
            ("below_the_share_threshold", [None, None, str(uuid7()), str(uuid7()), str(uuid7())], False),
        ]
    )
    def test_detects_unusable_session_ids(self, _name: str, session_ids: list[str | None], expected: bool) -> None:
        self._create_pageviews(session_ids)

        self.assertEqual(self._flagged(), expected)

    def test_recent_clean_window_clears_the_issue(self) -> None:
        self._create_pageviews([None, None, None], days_ago=20)
        self._create_pageviews([str(uuid7()), str(uuid7()), str(uuid7())], days_ago=1)

        self.assertFalse(self._flagged())

    def test_reason_counts_absent_ids_and_wrong_uuid_versions_apart(self) -> None:
        self._create_pageviews([None, str(uuid.uuid4()), str(uuid7())])

        with (
            patch(f"{MODULE}.MISSING_SESSION_ID_THRESHOLD", 0.5),
            patch(f"{MODULE}.MISSING_SESSION_ID_MIN_UNUSABLE", 2),
        ):
            reason = MissingSessionIdCheck().detect([self.team.id])[self.team.id][0].payload["reason"]

        self.assertIn("1 absent or not a UUID, 1 not a UUIDv7", reason)
