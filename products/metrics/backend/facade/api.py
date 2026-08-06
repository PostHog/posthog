"""Facade for metrics.

This is the ONLY module other products (and the presentation layer) are
allowed to import. Internal modules (query runners) stay behind this seam
so import-linter's strict-mode contract holds.
"""

import math
import datetime as dt
from typing import Any

from posthog.models import Team

from products.metrics.backend.anomaly import characterize_anomaly as _characterize_anomaly
from products.metrics.backend.facade.contracts import (
    CompanionMetric,
    IncidentContext,
    InvestigationResult,
    MetricAnomalyReport,
    MetricEventSample,
    MetricFilter,
    MetricPoint,
    MetricQueryClause,
    MetricQueryRequest,
    MetricSeries,
)
from products.metrics.backend.facade.enums import FilterOp, MetricAggregation
from products.metrics.backend.formula import evaluate, parse_formula
from products.metrics.backend.has_metrics_query_runner import team_has_metrics as _team_has_metrics
from products.metrics.backend.investigation import investigate as _investigate
from products.metrics.backend.metric_attributes_query_runner import (
    MetricAttributeKeysQueryRunner,
    MetricAttributeValuesQueryRunner,
)
from products.metrics.backend.metric_event_samples_query_runner import MetricEventSamplesQueryRunner
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
    by_labels: dict[tuple[tuple[str, str], ...], dict[str, float | None]] = {}
    for row in rows:
        key = tuple(sorted(row["labels"].items()))
        by_labels.setdefault(key, {})[row["time"]] = row["value"]

    # Rank and truncate on the sparse values BEFORE zero-filling, so a
    # high-cardinality group-by never materializes label_sets x grid points
    # only to throw most of them away. Zero-filled points contribute nothing
    # to the magnitude, so the ranking is identical either way.
    ranked = sorted(
        by_labels.items(), key=lambda item: (-sum(abs(v) for v in item[1].values() if v is not None), item[0])
    )
    return [
        MetricSeries(
            labels=dict(key),
            points=tuple(MetricPoint(time=time, value=values.get(time, 0.0)) for time in grid),
            metric_name=metric_name,
            clause=clause_name,
        )
        for key, values in ranked[:MAX_SERIES_PER_CLAUSE]
    ]


def _resolve_runner_aggregation(clause: MetricQueryClause) -> str:
    if clause.aggregation == MetricAggregation.QUANTILE and clause.quantile == 0.95:
        return "p95"
    if clause.aggregation == MetricAggregation.HISTOGRAM_QUANTILE:
        return "histogram_quantile"
    if clause.aggregation in _RUNNER_AGGREGATIONS:
        return _RUNNER_AGGREGATIONS[clause.aggregation]
    raise ValueError(f"aggregation {clause.aggregation.value!r} is not supported yet")


def _evaluate_formula_point(
    node: Any, per_clause_points: dict[str, tuple[MetricPoint, ...]], index: int
) -> float | None:
    """One formula grid point. A null (gap) in any input propagates as a
    gap, and a result the formula overflowed to inf/NaN becomes a gap too —
    same policy as the per-clause aggregates."""
    values: dict[str, float] = {}
    for name, pts in per_clause_points.items():
        value = pts[index].value
        if value is None:
            return None
        values[name] = value
    result = evaluate(node, values)
    return result if math.isfinite(result) else None


def _evaluate_formula(
    formula_text: str, series_by_clause: dict[str, list[MetricSeries]], grid: list[str]
) -> list[MetricSeries]:
    """Combine clause results point-by-point on the shared grid.

    Series are matched across clauses by exact label-set equality
    (Prometheus-style one-to-one vector matching); a clause that produced a
    single ungrouped series is broadcast to every label-set instead. A
    label-set missing from any non-broadcast clause is dropped.
    """
    node = parse_formula(formula_text, frozenset(series_by_clause))

    broadcasts: dict[str, MetricSeries] = {}
    grouped: dict[str, dict[tuple[tuple[str, str], ...], MetricSeries]] = {}
    for name, series_list in series_by_clause.items():
        if len(series_list) == 1 and not series_list[0].labels:
            broadcasts[name] = series_list[0]
        else:
            grouped[name] = {tuple(sorted(s.labels.items())): s for s in series_list}

    if grouped:
        label_sets: set[tuple[tuple[str, str], ...]] = set.intersection(
            *(set(by_labels) for by_labels in grouped.values())
        )
    else:
        label_sets = {()}

    result: list[MetricSeries] = []
    for label_set in sorted(label_sets):
        per_clause_points: dict[str, tuple[MetricPoint, ...]] = {
            name: (grouped[name][label_set].points if name in grouped else broadcasts[name].points)
            for name in series_by_clause
        }
        points = tuple(
            MetricPoint(time=time, value=_evaluate_formula_point(node, per_clause_points, index))
            for index, time in enumerate(grid)
        )
        result.append(MetricSeries(labels=dict(label_set), points=points, metric_name=None, clause="formula"))
    return result


def run_metric_query(*, team: Team, request: MetricQueryRequest) -> list[MetricSeries]:
    """Execute a metric query and return one `MetricSeries` per
    (clause, label-set) pair — a single ungrouped clause yields exactly one
    series with empty labels, so consumers never branch on single-vs-multi.

    Every series of every clause shares one bucket grid (the union of
    observed buckets, zero-filled), which is what makes cross-series and
    cross-clause math line up. Series per clause are capped at
    `MAX_SERIES_PER_CLAUSE`, keeping the largest ones.

    With `formula` set, only the formula result series are returned
    (`clause="formula"`); request the clauses separately if you need the
    inputs too. The presentation layer surfaces `ValueError` as a 400.
    """
    rows_by_clause: dict[str, list[dict[str, Any]]] = {}
    for clause in request.clauses:
        runner_aggregation = _resolve_runner_aggregation(clause)
        runner = MetricQueryRunner(
            team=team,
            metric_name=clause.metric_name,
            aggregation=runner_aggregation,
            date_from=request.date_from,
            date_to=request.date_to,
            filters=clause.filters,
            group_by=clause.group_by,
            interval=request.interval,
            quantile=clause.quantile if runner_aggregation == "histogram_quantile" else None,
            metric_type=clause.metric_type.value if clause.metric_type is not None else None,
        )
        rows_by_clause[clause.name] = runner.run()

    # Validate the formula before any early return so bad formulas always 400.
    formula_node_checked = (
        parse_formula(request.formula, frozenset(rows_by_clause)) if request.formula is not None else None
    )

    grid = sorted({row["time"] for rows in rows_by_clause.values() for row in rows})
    if not grid:
        empty_clause = "formula" if formula_node_checked is not None else request.clauses[0].name
        metric_name = None if formula_node_checked is not None else request.clauses[0].metric_name
        return [MetricSeries(labels={}, points=(), metric_name=metric_name, clause=empty_clause)]

    series_by_clause = {
        clause.name: _assemble_series(
            rows_by_clause[clause.name], metric_name=clause.metric_name, clause_name=clause.name, grid=grid
        )
        for clause in request.clauses
    }

    if request.formula is not None:
        return _evaluate_formula(request.formula, series_by_clause, grid)

    return [series for clause in request.clauses for series in series_by_clause[clause.name]]


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


def list_metric_attribute_keys(
    *,
    team: Team,
    search: str = "",
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List distinct attribute keys seen on the team's metrics, most frequent
    first, for the filter bar's key autocomplete.

    Datapoint and resource attributes are merged into one list (filters run
    with scope 'auto', so the split doesn't matter to callers); `service_name`
    is always surfaced when it matches the search. The window defaults to the
    last 7 days. Returns `{"name": str}` dicts. Raises `ValueError` for an
    out-of-range limit or an inverted window.
    """
    runner = MetricAttributeKeysQueryRunner(team=team, search=search, date_from=date_from, date_to=date_to, limit=limit)
    return runner.run()


def list_metric_attribute_values(
    *,
    team: Team,
    key: str,
    search: str = "",
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List observed values for one metric attribute key, most frequent first,
    for the filter bar's value autocomplete.

    `service_name`/`service.name` read the first-class column, matching how
    filters on it execute. The window defaults to the last 7 days. Returns
    `{"id": str, "name": str, "count": int}` dicts. Raises `ValueError` for an
    empty key, an out-of-range limit, or an inverted window.
    """
    runner = MetricAttributeValuesQueryRunner(
        team=team, key=key, search=search, date_from=date_from, date_to=date_to, limit=limit
    )
    return runner.run()


def list_metric_event_samples(
    *,
    team: Team,
    metric_name: str,
    date_from: dt.datetime,
    date_to: dt.datetime,
    trace_id: str | None = None,
    limit: int = 100,
) -> list[MetricEventSample]:
    """List individual metric emissions (the events model) for a metric,
    newest first.

    Each sample carries its value, attributes, and trace linkage, so the
    Samples view can render raw rows and pivot to the trace behind any one.
    Pass `trace_id` for the reverse pivot — every emission on a given trace.
    Raises `ValueError` for an empty metric name, an inverted window, or an
    out-of-range limit; the presentation layer surfaces these as 400s.
    """
    runner = MetricEventSamplesQueryRunner(
        team=team,
        metric_name=metric_name,
        date_from=date_from,
        date_to=date_to,
        trace_id=trace_id,
        limit=limit,
    )
    return [MetricEventSample(**row) for row in runner.run()]


def characterize_metric_anomaly(
    *,
    team: Team,
    metric_name: str,
    anomaly_from: dt.datetime,
    anomaly_to: dt.datetime,
    baseline_from: dt.datetime | None = None,
    baseline_to: dt.datetime | None = None,
    aggregation: str | None = None,
    quantile: float | None = None,
    filters: tuple[MetricFilter, ...] = (),
    candidate_keys: tuple[str, ...] | None = None,
) -> MetricAnomalyReport:
    """Characterize how a metric behaves in an anomaly window vs a baseline:
    summary statistics, change magnitude/direction, the onset bucket, and
    the label values that moved the most (drilling into up to four candidate
    keys, auto-discovered from the metric's attributes when not given).

    The baseline defaults to the window of equal length immediately before
    `anomaly_from`. `aggregation` defaults by the metric's OTel type
    (counter -> rate, gauge -> avg, histogram -> histogram_quantile 0.95).
    Raises `ValueError` for invalid windows/aggregations — the presentation
    layer surfaces these as 400s.
    """
    return _characterize_anomaly(
        team=team,
        metric_name=metric_name,
        anomaly_from=anomaly_from,
        anomaly_to=anomaly_to,
        baseline_from=baseline_from,
        baseline_to=baseline_to,
        aggregation=aggregation,
        quantile=quantile,
        filters=filters,
        candidate_keys=candidate_keys,
    )


def investigate(
    *,
    team: Team,
    metric_name: str,
    anomaly_from: dt.datetime,
    anomaly_to: dt.datetime,
    baseline_from: dt.datetime | None = None,
    baseline_to: dt.datetime | None = None,
    aggregation: str | None = None,
    quantile: float | None = None,
    filters: tuple[MetricFilter, ...] = (),
    candidate_keys: tuple[str, ...] | None = None,
    companions: tuple[CompanionMetric, ...] = (),
) -> InvestigationResult:
    """Investigate a metric symptom end to end and return one structured result.

    Builds on `characterize_metric_anomaly`: it characterizes the metric over
    the anomaly window, then characterizes each `companion` over the SAME window
    to confirm or rule it out (e.g. throughput flat -> not a traffic surge),
    classifies blast radius from the movers, implicates a service for the
    logs/traces pivot, and emits re-runnable chart specs.

    The result is the single shape the agent narrates, the in-app explorer
    renders, and the incident report serializes. Raises `ValueError` for invalid
    windows/aggregations — the presentation layer surfaces these as 400s.
    """
    return _investigate(
        team=team,
        metric_name=metric_name,
        anomaly_from=anomaly_from,
        anomaly_to=anomaly_to,
        baseline_from=baseline_from,
        baseline_to=baseline_to,
        aggregation=aggregation,
        quantile=quantile,
        filters=filters,
        candidate_keys=candidate_keys,
        companions=companions,
    )


def investigate_incident(*, team: Team, context: IncidentContext) -> InvestigationResult:
    """Investigate a fired alert's metric with no timestamp math on the caller.

    Derives the anomaly window straight from `context.fired_at` (an explicit
    UTC instant) — no parsing a fire time out of prose, no timezone guesswork —
    scopes to the implicated service, and runs the full investigation. Returns
    the same `InvestigationResult` as `investigate()`. This is the entry point
    an alert's "Investigate" action calls.
    """
    filters: tuple[MetricFilter, ...] = ()
    if context.service_name:
        filters = (MetricFilter(key="service_name", op=FilterOp.EQ, value=context.service_name),)
    return _investigate(
        team=team,
        metric_name=context.metric_name,
        anomaly_from=context.fired_at - context.lookback,
        anomaly_to=context.fired_at + context.leadout,
        filters=filters,
        companions=context.companions,
    )
