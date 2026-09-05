import pytest
from unittest.mock import MagicMock, patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.temporal.health_checks.traffic_stop import TrafficStopCheck


@pytest.mark.parametrize(
    "mock_rows, expected",
    [
        ([], {}),
        ([(42, 1400, 14)], {42: 100}),
        ([(1, 300, 8), (3, 5000, 10)], {1: 38, 3: 500}),
    ],
    ids=["all_healthy", "single_team_stopped", "multiple_teams_stopped"],
)
@patch("products.web_analytics.backend.temporal.health_checks.traffic_stop.execute_clickhouse_health_team_query")
def test_detect_traffic_stop(mock_query: MagicMock, mock_rows: list, expected: dict[int, int]) -> None:
    mock_query.return_value = mock_rows

    result = TrafficStopCheck().detect([1, 2, 3, 42])

    assert set(result.keys()) == set(expected.keys())
    for team_id, per_active_day in expected.items():
        issues = result[team_id]
        assert len(issues) == 1
        assert issues[0].severity == HealthIssue.Severity.CRITICAL
        # Rounded events-per-active-day is surfaced in the reason so the alert names the lost baseline.
        assert f"{per_active_day}/day" in issues[0].payload["reason"]
