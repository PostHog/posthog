"""Facade for metrics.

This is the ONLY module other products (and the presentation layer) are
allowed to import. Internal modules (query runners) stay behind this seam
so import-linter's strict-mode contract holds.
"""

import math
import datetime as dt
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError

from posthog.models import Team

if TYPE_CHECKING:
    from django.db.models import QuerySet

from products.metrics.backend.anomaly import characterize_anomaly as _characterize_anomaly
from products.metrics.backend.diagnostics import decompose_bucket as _decompose_bucket
from products.metrics.backend.facade.contracts import (
    CompanionMetric,
    IncidentContext,
    InvestigationResult,
    MetricAnomalyReport,
    MetricBucketDecomposition,
    MetricEventSample,
    MetricFilter,
    MetricPoint,
    MetricQueryClause,
    MetricQueryRequest,
    MetricSeries,
    MetricsOverview,
    MetricsPipelineRecord,
    PipelineActor,
    PipelineConfig,
    PipelineEvaluation,
    PipelineNotFoundError,
)
from products.metrics.backend.facade.enums import FilterOp, MetricAggregation, MetricType
from products.metrics.backend.formula import evaluate, parse_formula
from products.metrics.backend.has_metrics_query_runner import team_has_metrics as _team_has_metrics
from products.metrics.backend.investigation import investigate as _investigate
from products.metrics.backend.metric_attributes_query_runner import (
    MetricAttributeKeysQueryRunner,
    MetricAttributeValuesQueryRunner,
)
from products.metrics.backend.metric_event_samples_query_runner import MetricEventSamplesQueryRunner
from products.metrics.backend.metric_names_query_runner import cached_metric_names
from products.metrics.backend.metric_query_runner import MetricQueryRunner
from products.metrics.backend.metrics_overview_query_runner import MetricsOverviewQueryRunner
from products.metrics.backend.models import MetricsPipeline
from products.metrics.backend.pipeline_config import parse_pipeline_config as _parse_pipeline_config
from products.metrics.backend.pipeline_evaluation import evaluate_pipeline as _evaluate_pipeline

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
    rows: list[dict[str, Any]], *, metric_name: str, clause_name: str, grid: list[str], zero_fill: bool = True
) -> list[MetricSeries]:
    """Split bucketed rows into one series per label-set, laid onto the shared
    grid so every series (and later, every clause of a formula) has identical
    timestamps. Buckets a series did not report become 0.0, or None when
    `zero_fill` is False."""
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
    filler: float | None = 0.0 if zero_fill else None
    return [
        MetricSeries(
            labels=dict(key),
            points=tuple(MetricPoint(time=time, value=values.get(time, filler)) for time in grid),
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
            rows_by_clause[clause.name],
            metric_name=clause.metric_name,
            clause_name=clause.name,
            grid=grid,
            zero_fill=request.zero_fill,
        )
        for clause in request.clauses
    }

    if request.formula is not None:
        return _evaluate_formula(request.formula, series_by_clause, grid)

    return [series for clause in request.clauses for series in series_by_clause[clause.name]]


def _to_pipeline_record(pipeline: "MetricsPipeline") -> MetricsPipelineRecord:
    created_by = None
    if pipeline.created_by is not None:
        created_by = PipelineActor(
            id=pipeline.created_by.id,
            email=pipeline.created_by.email,
            first_name=pipeline.created_by.first_name,
        )
    return MetricsPipelineRecord(
        id=str(pipeline.id),
        name=pipeline.name,
        description=pipeline.description,
        config=pipeline.config,
        enabled=pipeline.enabled,
        created_at=pipeline.created_at.isoformat(),
        created_by=created_by,
        updated_at=pipeline.updated_at.isoformat() if pipeline.updated_at else None,
    )


def _pipeline_queryset(team: Team) -> "QuerySet[MetricsPipeline]":
    return MetricsPipeline.objects.for_team(team.pk).filter(deleted=False).select_related("created_by")


def list_pipelines(*, team: Team) -> list[MetricsPipelineRecord]:
    """List the team's pipelines, newest first."""
    return [_to_pipeline_record(p) for p in _pipeline_queryset(team).order_by("-created_at")]


def get_pipeline(*, team: Team, pipeline_id: str) -> MetricsPipelineRecord:
    """Fetch one pipeline. Raises `PipelineNotFoundError` for an unknown or
    deleted id — the presentation layer surfaces it as a 404."""
    try:
        return _to_pipeline_record(_pipeline_queryset(team).get(id=pipeline_id))
    except (MetricsPipeline.DoesNotExist, ValueError, ValidationError) as e:
        raise PipelineNotFoundError(pipeline_id) from e


def _validated_config(config: dict) -> dict:
    """Validate a config and fill the optional list keys.

    A PATCH sends `partial=True`, which DRF propagates into the nested config
    serializer, so its `edges`/`variables` defaults are skipped and the keys can
    be absent. The parser tolerates that, but readers should not have to, so the
    stored config always carries every top-level key.
    """
    _parse_pipeline_config(config)
    return {**config, "edges": config.get("edges") or [], "variables": config.get("variables") or []}


def create_pipeline(
    *, team: Team, created_by_id: int | None, name: str, description: str, config: dict, enabled: bool = True
) -> MetricsPipelineRecord:
    """Create a pipeline. Raises `ValueError` when `config` is invalid."""
    pipeline = MetricsPipeline.objects.for_team(team.pk).create(
        team_id=team.pk,
        created_by_id=created_by_id,
        name=name,
        description=description,
        config=_validated_config(config),
        enabled=enabled,
    )
    return _to_pipeline_record(_pipeline_queryset(team).get(id=pipeline.id))


def update_pipeline(
    *,
    team: Team,
    pipeline_id: str,
    name: str | None = None,
    description: str | None = None,
    config: dict | None = None,
    enabled: bool | None = None,
) -> MetricsPipelineRecord:
    """Patch a pipeline; None leaves a field untouched. Raises
    `PipelineNotFoundError` / `ValueError` like its siblings."""
    try:
        pipeline = _pipeline_queryset(team).get(id=pipeline_id)
    except (MetricsPipeline.DoesNotExist, ValueError, ValidationError) as e:
        raise PipelineNotFoundError(pipeline_id) from e
    if config is not None:
        pipeline.config = _validated_config(config)
    if name is not None:
        pipeline.name = name
    if description is not None:
        pipeline.description = description
    if enabled is not None:
        pipeline.enabled = enabled
    pipeline.save()
    return _to_pipeline_record(pipeline)


def soft_delete_pipeline(*, team: Team, pipeline_id: str) -> None:
    """Soft-delete a pipeline: the row keeps its activity history and the
    project-tree entry is removed. Raises `PipelineNotFoundError` for an
    unknown id."""
    try:
        pipeline = _pipeline_queryset(team).get(id=pipeline_id)
    except (MetricsPipeline.DoesNotExist, ValueError, ValidationError) as e:
        raise PipelineNotFoundError(pipeline_id) from e
    pipeline.deleted = True
    pipeline.save()


def parse_pipeline_config(data: object) -> "PipelineConfig":
    """Parse and validate a stored pipeline topology config. Raises
    `ValueError` with a path-qualified message on the first rejection — the
    presentation layer surfaces these as 400s."""
    return _parse_pipeline_config(data)


def evaluate_pipeline(
    *,
    team: Team,
    config: "PipelineConfig",
    date_from: dt.datetime,
    date_to: dt.datetime,
    variable_values: dict[str, str] | None = None,
) -> "PipelineEvaluation":
    """Evaluate a pipeline topology's health over one window: every node
    stat's value + warn/crit verdict, every edge's throughput vs its shifted
    baseline window, and the derived alert strip. Raises `ValueError` for
    unknown variable keys/values — the presentation layer surfaces these as
    400s."""

    def run_query(request: MetricQueryRequest) -> list[MetricSeries]:
        return run_metric_query(team=team, request=request)

    return _evaluate_pipeline(
        config=config,
        run_query=run_query,
        date_from=date_from,
        date_to=date_to,
        variable_values=variable_values,
    )


def list_metric_names(
    *,
    team: Team,
    search: str = "",
    limit: int = 100,
    services: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """List distinct metric names for the team's picker.

    Returns a list of `{"name": str, "metric_type": str}` dicts ordered by
    most-recently-seen, with exact-name matches floated to the top.
    Passing `services` narrows the list to names those services reported.
    Raises `ValueError` for an out-of-range limit or too many services.

    The unsearched list is cached per team and service scope for a minute;
    searches are not.
    """
    return cached_metric_names(team=team, search=search, limit=limit, services=services)


def get_metrics_overview(*, team: Team, lookback: dt.timedelta | None = None) -> MetricsOverview:
    """Ingestion rollup for the overview page: freshness of the newest
    datapoint plus window-scoped metric/series counts per service.

    Raises `ValueError` for a non-positive lookback.
    """
    if lookback is None:
        return MetricsOverviewQueryRunner(team=team).run()
    return MetricsOverviewQueryRunner(team=team, lookback=lookback).run()


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
    filters: Sequence[MetricFilter] = (),
    metric_type: MetricType | None = None,
    limit: int = 100,
) -> list[MetricEventSample]:
    """List individual metric emissions (the events model) for a metric,
    newest first.

    Each sample carries its value, attributes, and trace linkage, so the
    Samples view can render raw rows and pivot to the trace behind any one.
    Pass `trace_id` for the reverse pivot — every emission on a given trace.
    `filters` and `metric_type` narrow the emissions to the same series a
    `run_metric_query` call with those arguments charts, so a filtered view
    and its chart agree. Both are matched against the emission's series, so
    an emission whose series row hasn't been ingested yet drops out once
    either is set.
    Raises `ValueError` for an empty metric name, an inverted window, an
    invalid regex filter, or an out-of-range limit; the presentation layer
    surfaces these as 400s.
    """
    runner = MetricEventSamplesQueryRunner(
        team=team,
        metric_name=metric_name,
        date_from=date_from,
        date_to=date_to,
        trace_id=trace_id,
        filters=filters,
        metric_type=metric_type,
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


def explain_metric_bucket(
    *,
    team: Team,
    metric_name: str,
    aggregation: str,
    bucket_start: dt.datetime,
    interval: str,
    filters: Sequence[MetricFilter] = (),
    metric_type: MetricType | None = None,
    quantile: float | None = None,
) -> MetricBucketDecomposition:
    """Take one chart point apart and show how it was built.

    Returns the series that reported in the bucket, the samples each sent, and
    the two reductions that combined them, alongside both the value the product
    would plot and the value recomputed independently from the raw samples.
    Reading them side by side is what makes an aggregation bug visible instead
    of merely plausible. The presentation layer surfaces `ValueError` as a 400.
    """
    return _decompose_bucket(
        team=team,
        metric_name=metric_name,
        aggregation=aggregation,
        bucket_start=bucket_start,
        interval=interval,
        filters=filters,
        metric_type=metric_type.value if metric_type is not None else None,
        quantile=quantile,
    )
