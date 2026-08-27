import pytest
from unittest.mock import MagicMock, patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.temporal.health_checks.missing_session_id import MissingSessionIdCheck


@pytest.mark.parametrize(
    "mock_rows, expected_teams",
    [
        ([], set()),
        ([(42, 20_000, 6_000)], {42}),
        ([(1, 50_000, 40_000), (3, 12_000, 800)], {1, 3}),
    ],
    ids=["all_healthy", "single_team_missing_session_id", "multiple_teams_flagged"],
)
@patch("products.web_analytics.backend.temporal.health_checks.missing_session_id.execute_clickhouse_health_team_query")
def test_detect_missing_session_id(mock_query: MagicMock, mock_rows: list, expected_teams: set) -> None:
    mock_query.return_value = mock_rows

    result = MissingSessionIdCheck().detect([1, 2, 3, 42])

    assert set(result.keys()) == expected_teams
    for team_id in expected_teams:
        issues = result[team_id]
        assert len(issues) == 1
        assert issues[0].severity == HealthIssue.Severity.WARNING
        assert "$session_id" in issues[0].payload["reason"]


@patch("products.web_analytics.backend.temporal.health_checks.missing_session_id.execute_clickhouse_health_team_query")
def test_reason_reports_share(mock_query: MagicMock) -> None:
    mock_query.return_value = [(7, 20_000, 5_000)]

    result = MissingSessionIdCheck().detect([7])

    assert "25.0%" in result[7][0].payload["reason"]
