"""Facade for metrics.

This is the ONLY module other products (and the presentation layer) are
allowed to import. Internal modules (query runners) stay behind this seam
so import-linter's strict-mode contract holds.
"""

import datetime as dt
from typing import Any

from posthog.models import Team

from products.metrics.backend.has_metrics_query_runner import team_has_metrics as _team_has_metrics
from products.metrics.backend.metric_names_query_runner import MetricNamesQueryRunner
from products.metrics.backend.metric_query_runner import MetricQueryRunner


def team_has_metrics(team: Team) -> bool:
    """Return True if the given team has ingested at least one metric."""
    return _team_has_metrics(team)


def query_metric(
    *,
    team: Team,
    metric_name: str,
    aggregation: str,
    date_from: dt.datetime,
    date_to: dt.datetime,
) -> list[dict[str, Any]]:
    """Run a single-metric time-series query and return the bucketed points.

    Returns a list of `{"time": iso_string, "value": float}` dicts ordered by
    time ascending. Raises `ValueError` for unsupported aggregations or an
    inverted date range — the presentation layer surfaces these as 400s.
    """
    runner = MetricQueryRunner(
        team=team,
        metric_name=metric_name,
        aggregation=aggregation,
        date_from=date_from,
        date_to=date_to,
    )
    return runner.run()


def list_metric_names(
    *,
    team: Team,
    search: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List distinct metric names for the team's picker.

    Returns a list of `{"name": str, "metric_type": str}` dicts ordered by
    most-recently-seen, with exact-name matches floated to the top.
    Raises `ValueError` for an out-of-range limit.
    """
    runner = MetricNamesQueryRunner(team=team, search=search, limit=limit)
    return runner.run()
