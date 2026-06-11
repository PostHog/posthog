"""Facade for metrics.

This is the ONLY module other products (and the presentation layer) are
allowed to import. Internal modules (query runners) stay behind this seam
so import-linter's strict-mode contract holds.
"""

from typing import Any

from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricPoint, MetricQueryRequest, MetricSeries
from products.metrics.backend.facade.enums import MetricAggregation
from products.metrics.backend.has_metrics_query_runner import team_has_metrics as _team_has_metrics
from products.metrics.backend.metric_names_query_runner import MetricNamesQueryRunner
from products.metrics.backend.metric_query_runner import MetricQueryRunner

# MetricQueryRunner still speaks the legacy aggregation strings; this shrinks
# as later PRs teach the runner the remaining MetricAggregation values.
_RUNNER_AGGREGATIONS: dict[MetricAggregation, str] = {
    MetricAggregation.SUM: "sum",
    MetricAggregation.AVG: "avg",
    MetricAggregation.COUNT: "count",
}


def team_has_metrics(team: Team) -> bool:
    """Return True if the given team has ingested at least one metric."""
    return _team_has_metrics(team)


def run_metric_query(*, team: Team, request: MetricQueryRequest) -> list[MetricSeries]:
    """Execute a metric query and return one `MetricSeries` per
    (clause, label-set) pair — a single ungrouped clause yields exactly one
    series with empty labels, so consumers never branch on single-vs-multi.

    Current scope: one clause; filters, group_by, interval, formula and the
    rate/histogram aggregations raise `ValueError` until their PRs land.
    The presentation layer surfaces `ValueError` as a 400.
    """
    if len(request.clauses) != 1:
        raise ValueError("multi-clause queries are not supported yet")
    if request.formula is not None:
        raise ValueError("formulas are not supported yet")
    if request.interval is not None:
        raise ValueError("explicit intervals are not supported yet")

    clause = request.clauses[0]
    if clause.group_by:
        raise ValueError("group_by is not supported yet")

    if clause.aggregation == MetricAggregation.QUANTILE and clause.quantile == 0.95:
        runner_aggregation = "p95"
    elif clause.aggregation in _RUNNER_AGGREGATIONS:
        runner_aggregation = _RUNNER_AGGREGATIONS[clause.aggregation]
    else:
        raise ValueError(f"aggregation {clause.aggregation.value!r} is not supported yet")

    runner = MetricQueryRunner(
        team=team,
        metric_name=clause.metric_name,
        aggregation=runner_aggregation,
        date_from=request.date_from,
        date_to=request.date_to,
        filters=clause.filters,
    )
    points = tuple(MetricPoint(time=row["time"], value=row["value"]) for row in runner.run())
    return [MetricSeries(labels={}, points=points, metric_name=clause.metric_name, clause=clause.name)]


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
