import pytest
from unittest.mock import MagicMock, patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.temporal.health_checks.reverse_proxy import (
    REVERSE_PROXY_LOOKBACK_DAYS,
    ReverseProxyCheck,
)

_QUERY_PATH = "products.web_analytics.backend.temporal.health_checks.reverse_proxy.execute_clickhouse_health_team_query"


@pytest.mark.parametrize(
    "mock_rows, expected_teams",
    [
        ([], set()),
        ([(42,)], {42}),
        ([(1,), (3,)], {1, 3}),
    ],
    ids=["all_healthy", "single_team_no_proxy", "multiple_teams_mixed"],
)
@patch(_QUERY_PATH)
def test_detect_maps_rows_to_issues(mock_query: MagicMock, mock_rows: list, expected_teams: set) -> None:
    mock_query.return_value = mock_rows

    result = ReverseProxyCheck().detect([1, 2, 3, 42])

    assert set(result.keys()) == expected_teams
    for team_id in expected_teams:
        issues = result[team_id]
        assert len(issues) == 1
        assert issues[0].severity == HealthIssue.Severity.WARNING


@patch(_QUERY_PATH)
def test_detect_judges_over_a_multi_day_window_with_a_minimum_event_floor(mock_query: MagicMock) -> None:
    # Guards the flapping fix: a one-day window drops a project on any zero-traffic day, and
    # without a floor the check flags a project it has too little browser traffic to judge.
    mock_query.return_value = []

    ReverseProxyCheck().detect([1])

    _, kwargs = mock_query.call_args
    assert REVERSE_PROXY_LOOKBACK_DAYS > 1
    assert kwargs["lookback_days"] == REVERSE_PROXY_LOOKBACK_DAYS
    assert kwargs["params"]["min_browser_events"] >= 1
