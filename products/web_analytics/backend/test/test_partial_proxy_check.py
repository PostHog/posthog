import pytest
from unittest.mock import MagicMock, patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.temporal.health_checks.partial_proxy import MIN_EVENTS_PER_HOST, PartialProxyCheck


@pytest.mark.parametrize(
    "mock_rows, expected_flagged",
    [
        (
            [],
            {},
        ),
        (
            [(1, "www.example.com", True, 100)],
            {},
        ),
        (
            [(1, "www.example.com", False, 100)],
            {},
        ),
        (
            [
                (1, "www.example.com", True, 100),
                (1, "app.example.com", True, 200),
            ],
            {},
        ),
        (
            [
                (1, "www.example.com", False, 100),
                (1, "app.example.com", False, 200),
            ],
            {},
        ),
        (
            [
                (1, "www.example.com", False, 100),
                (1, "app.example.com", True, 200),
            ],
            {1: (["app.example.com"], ["www.example.com"])},
        ),
        (
            [
                (1, "www.example.com", False, 100),
                (1, "app.example.com", True, 200),
                (1, "docs.example.com", True, 150),
                (1, "blog.example.com", False, 80),
                (2, "other.com", True, 500),
            ],
            {
                1: (
                    ["app.example.com", "docs.example.com"],
                    ["blog.example.com", "www.example.com"],
                ),
            },
        ),
    ],
    ids=[
        "no_events",
        "single_proxied_host",
        "single_unproxied_host",
        "all_proxied_two_hosts",
        "all_unproxied_two_hosts",
        "mixed_one_each",
        "mixed_multi_with_unrelated_healthy_team",
    ],
)
@patch("products.web_analytics.backend.temporal.health_checks.partial_proxy.execute_clickhouse_health_team_query")
def test_partial_proxy_detect(
    mock_query: MagicMock,
    mock_rows: list[tuple[int, str, bool, int]],
    expected_flagged: dict[int, tuple[list[str], list[str]]],
) -> None:
    mock_query.return_value = mock_rows
    check = PartialProxyCheck()

    result = check.detect([1, 2])

    assert set(result.keys()) == set(expected_flagged.keys())

    for team_id, (proxied, unproxied) in expected_flagged.items():
        issues = result[team_id]
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == HealthIssue.Severity.WARNING
        assert "Reverse proxy is only configured on some hostnames" in issue.payload["reason"]
        assert issue.payload["proxied_hosts"] == proxied
        assert issue.payload["unproxied_hosts"] == unproxied


@patch("products.web_analytics.backend.temporal.health_checks.partial_proxy.execute_clickhouse_health_team_query")
def test_partial_proxy_passes_min_events_per_host(mock_query: MagicMock) -> None:
    mock_query.return_value = []
    PartialProxyCheck().detect([1])

    _args, kwargs = mock_query.call_args
    assert kwargs["params"]["min_events_per_host"] == MIN_EVENTS_PER_HOST
    assert kwargs["lookback_days"] > 0
