from unittest.mock import MagicMock, patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.temporal.health_checks.reverse_proxy import (
    MIN_EVENTS,
    REVERSE_PROXY_LOOKBACK_DAYS,
    ReverseProxyCheck,
)


@patch("products.web_analytics.backend.temporal.health_checks.reverse_proxy.execute_clickhouse_health_team_query")
def test_reverse_proxy_detect_flags_returned_teams(mock_query: MagicMock) -> None:
    mock_query.return_value = [(1,), (2,)]

    result = ReverseProxyCheck().detect([1, 2, 3])

    assert set(result.keys()) == {1, 2}
    for team_id in (1, 2):
        issues = result[team_id]
        assert len(issues) == 1
        assert issues[0].severity == HealthIssue.Severity.WARNING


@patch("products.web_analytics.backend.temporal.health_checks.reverse_proxy.execute_clickhouse_health_team_query")
def test_reverse_proxy_gates_on_volume_and_multi_day_lookback(mock_query: MagicMock) -> None:
    mock_query.return_value = []

    ReverseProxyCheck().detect([1])

    _args, kwargs = mock_query.call_args
    assert kwargs["params"]["min_events"] == MIN_EVENTS
    assert MIN_EVENTS > 0
    assert kwargs["lookback_days"] == REVERSE_PROXY_LOOKBACK_DAYS
    assert REVERSE_PROXY_LOOKBACK_DAYS > 1
