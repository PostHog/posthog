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
    MetricAggregation.RATE: "rate",
    MetricAggregation.INCREASE: "increase",
}


def team_has_metrics(team: Team) -> bool:
    """Return True if the given team has ingested at least one metric."""
    return _team_has_metrics(team)


# Hard cap on series returned per clause; the largest series (by summed
# absolute value) win so the most significant groups survive truncation.
MAX_SERIES_PER_CLAUSE = 100


def _assemble_series(
    rows: list[dict[str, Any]], *, metric_name: str, clause_name: str, grid: list[str]
) -> list[MetricSeries]:
    """Split bucketed rows into one series per label-set, zero-filled onto
    the shared grid so every series (and later, every clause of a formula)
    has identical timestamps."""
    by_labels: dict[tuple[tuple[str, str], ...], dict[str, float]] = {}
    for row in rows:
        key = tuple(sorted(row["labels"].items()))
        by_labels.setdefault(key, {})[row["time"]] = row["value"]

    series = [
        MetricSeries(
            labels=dict(key),
            points=tuple(MetricPoint(time=time, value=values.get(time, 0.0)) for time in grid),
            metric_name=metric_name,
            clause=clause_name,
        )
        for key, values in by_labels.items()
    ]
    series.sort(key=lambda s: (-sum(abs(p.value) for p in s.points), tuple(sorted(s.labels.items()))))
    return series[:MAX_SERIES_PER_CLAUSE]


def run_metric_query(*, team: Team, request: MetricQueryRequest) -> list[MetricSeries]:
    """Execute a metric query and return one `MetricSeries` per
    (clause, label-set) pair — a single ungrouped clause yields exactly one
    series with empty labels, so consumers never branch on single-vs-multi.

    All series share one bucket grid (the union of observed buckets,
    zero-filled), which is what makes cross-series and cross-clause math
    line up. Series per clause are capped at `MAX_SERIES_PER_CLAUSE`,
    keeping the largest ones.

    Current scope: one clause; multi-clause and formula raise `ValueError`
    until their PRs land. The presentation layer surfaces `ValueError` as
    a 400.
    """
    if len(request.clauses) != 1:
        raise ValueError("multi-clause queries are not supported yet")
    if request.formula is not None:
        raise ValueError("formulas are not supported yet")

    clause = request.clauses[0]

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
        group_by=clause.group_by,
        interval=request.interval,
    )
    rows = runner.run()
    if not rows:
        return [MetricSeries(labels={}, points=(), metric_name=clause.metric_name, clause=clause.name)]

    grid = sorted({row["time"] for row in rows})
    return _assemble_series(rows, metric_name=clause.metric_name, clause_name=clause.name, grid=grid)


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
