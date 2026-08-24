import pytest
from unittest.mock import MagicMock, patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.temporal.health_checks.no_pageleave_events import NoPageleaveEventsCheck


@pytest.mark.parametrize(
    "mock_rows, expected_teams",
    [
        ([], set()),
        ([(42, 100, 8)], {42}),
        ([(1, 200, 190), (3, 120, 10)], {1, 3}),
    ],
    ids=["all_healthy", "single_team_missing_pageleave", "multiple_teams_mixed"],
)
@patch("products.web_analytics.backend.temporal.health_checks.no_pageleave_events.execute_clickhouse_health_team_query")
def test_detect_no_pageleave_events(mock_query: MagicMock, mock_rows: list, expected_teams: set) -> None:
    mock_query.return_value = mock_rows

    result = NoPageleaveEventsCheck().detect([1, 2, 3, 42])

    assert set(result.keys()) == expected_teams
    for team_id in expected_teams:
        issues = result[team_id]
        assert len(issues) == 1
        assert issues[0].severity == HealthIssue.Severity.WARNING
        assert "$pageleave" in issues[0].payload["reason"]


@patch("products.web_analytics.backend.temporal.health_checks.no_pageleave_events.execute_clickhouse_health_team_query")
def test_detect_estimates_pageleave_volume_ratio(mock_query: MagicMock) -> None:
    # A single-page app packs many $pageview into one session, so the estimate is small.
    mock_query.return_value = [(42, 1000, 80)]

    issues = NoPageleaveEventsCheck().detect([42])[42]

    assert issues[0].payload["estimated_pageleave_ratio"] == pytest.approx(0.08)


@patch("products.web_analytics.backend.temporal.health_checks.no_pageleave_events.execute_clickhouse_health_team_query")
def test_detect_omits_ratio_without_sessions(mock_query: MagicMock) -> None:
    mock_query.return_value = [(42, 100, 0)]

    issues = NoPageleaveEventsCheck().detect([42])[42]

    assert "estimated_pageleave_ratio" not in issues[0].payload
