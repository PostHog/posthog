import pytest
from unittest.mock import MagicMock, patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.temporal.health_checks.no_pageleave_events import NoPageleaveEventsCheck


@pytest.mark.parametrize(
    "mock_rows, expected_teams",
    [
        ([], set()),
        ([(42,)], {42}),
        ([(1,), (3,)], {1, 3}),
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
