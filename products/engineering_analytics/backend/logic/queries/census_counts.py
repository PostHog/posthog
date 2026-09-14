"""Latest per-team test-file counts from the daily census events, read from ``events``
through the curated handle so team scope stays in one place (the ``llm_spend`` pattern)."""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.logic._shared import WindowedCount
from products.engineering_analytics.backend.logic.census import CENSUS_EVENT
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT
        toString(properties.owner_team) AS owner_team,
        argMax(accurateCastOrNull(properties.test_file_count, 'Int64'), timestamp) AS test_file_count,
        argMaxIf(
            accurateCastOrNull(properties.test_file_count, 'Int64'),
            timestamp,
            timestamp < {date_from}
        ) AS test_file_count_prior
    FROM events
    WHERE event = {census_event}
        AND properties.repository = {repository}
        AND timestamp >= {scan_from}
        AND timestamp <= {date_to}
    GROUP BY owner_team
"""


def query_census_counts(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    scan_from: datetime,
    date_to: datetime,
) -> dict[str, WindowedCount]:
    """``owner_team -> test-file counts``; empty when no census ran."""
    if not curated.repository:
        return {}
    response = curated.run(
        _SELECT,
        query_type="engineering_analytics.team_test_census",
        placeholders={
            "census_event": ast.Constant(value=CENSUS_EVENT),
            "repository": ast.Constant(value=curated.repository),
            "date_from": ast.Constant(value=date_from),
            "scan_from": ast.Constant(value=scan_from),
            "date_to": ast.Constant(value=date_to),
        },
    )
    return {
        owner_team: WindowedCount(
            current=int(count) if count is not None else None,
            prior=int(prior) if prior is not None else None,
        )
        for owner_team, count, prior in (response.results or [])
        if owner_team
    }
