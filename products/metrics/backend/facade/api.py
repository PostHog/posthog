"""Facade for metrics.

This is the ONLY module other products (and the presentation layer) are
allowed to import. Internal modules (query runners) stay behind this seam
so import-linter's strict-mode contract holds.
"""

import math
import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from functools import partial
from typing import Any

from django.conf import settings
from django.db import connection

import structlog

from posthog.schema import DateRange, MetricsDashboardVariable, MetricsDashboardVariableSource

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.utils.parallel import run_in_parallel_threads
from posthog.models import Team, User
from posthog.scopes import APIScopeObject

from products.error_tracking.backend.facade.api import list_latest_spike_events
from products.metrics.backend.anomaly import characterize_anomaly as _characterize_anomaly
from products.metrics.backend.date_range import metrics_query_date_range
from products.metrics.backend.derived import (
    DerivedMetric,
    DerivedMetricQueryRunner,
    derived_metric_resources as _derived_metric_resources,
    derived_metrics_enabled,
    get_derived_metric,
    is_derived_metric_name as _is_derived_metric_name,
    list_derived_metric_names,
    team_has_derived_sources,
)
from products.metrics.backend.facade.contracts import (
    CompanionMetric,
    DashboardImportRequest,
    DashboardImportStatus,
    DashboardTemplateSummary,
    DerivedSeriesStatus,
    IncidentContext,
    InvestigationResult,
    MetricAnomalyReport,
    MetricErrorSpike,
    MetricEventSample,
    MetricFilter,
    MetricPoint,
    MetricQueryClause,
    MetricQueryCount,
    MetricQueryRequest,
    MetricSeries,
    MetricsOverview,
    PanelQueryCheckRequest,
    PanelQueryCheckResult,
    RecordingRule,
    SuggestedDashboard,
)
from products.metrics.backend.facade.enums import (
    DashboardTemplateStatus,
    FilterOp,
    MetricAggregation,
    MetricRangeFunction,
    MetricType,
)
from products.metrics.backend.formula import evaluate, parse_formula
from products.metrics.backend.has_metrics_query_runner import team_has_metrics as _team_has_metrics
from products.metrics.backend.investigation import investigate as _investigate
from products.metrics.backend.metric_attributes_query_runner import (
    MetricAttributeKeysQueryRunner,
    MetricAttributeValuesQueryRunner,
)
from products.metrics.backend.metric_event_samples_query_runner import MetricEventSamplesQueryRunner
from products.metrics.backend.metric_names_query_runner import (
    MetricNamesQueryRunner,
    cached_metric_names,
    fold_classic_histograms,
    name_matches,
)
from products.metrics.backend.metric_query_runner import (
    MAX_QUERY_SPAN,
    MAX_RAW_SERIES,
    MetricQueryRunner,
    _align_to_interval,
    _interval_step,
    _pick_interval,
)
from products.metrics.backend.metric_samples_query_runner import build_metric_query_runner
from products.metrics.backend.metrics_overview_query_runner import MetricsOverviewQueryRunner
from products.metrics.backend.promql import run_promql_instant, run_promql_range
from products.metrics.backend.query_concurrency import query_concurrency_slots
from products.metrics.backend.query_counts import (
    list_metric_query_counts as _list_metric_query_counts,
    record_metric_queries,
    record_promql_query as _record_promql_query,
)
from products.metrics.backend.recording_rules import logic as recording_rule_logic
from products.metrics.backend.variable_options import check_options_window, compile_regex, list_variable_options
from products.metrics.backend.variables import from_dashboard, with_values

logger = structlog.get_logger(__name__)

# MetricQueryRunner still speaks the legacy aggregation strings; this shrinks
# as later PRs teach the runner the remaining MetricAggregation values.
# NONE maps to no aggregation, which is not a string.
_RUNNER_AGGREGATIONS: dict[MetricAggregation, str] = {
    MetricAggregation.SUM: "sum",
    MetricAggregation.AVG: "avg",
    MetricAggregation.COUNT: "count",
    MetricAggregation.MIN: "min",
    MetricAggregation.MAX: "max",
    MetricAggregation.RATE: "rate",
    MetricAggregation.INCREASE: "increase",
}


def team_has_metrics(team: Team) -> bool:
    """Return True if the given team has ingested at least one metric."""
    return _team_has_metrics(team)


def _units_by_fingerprint(team: Team, metric_names: set[str]) -> dict[int, str]:
    """One ClickHouse lookup of the ingested UCUM unit per physical series,
    keyed by `series_fingerprint` and read from `metric_series` (the same table
    the catalog reads). Per-fingerprint rather than per-name so a metric whose
    series disagree on the unit never lends one series' unit to another.
    Returns only series with a non-empty unit; a series with no unit is simply
    absent, so callers use `.get(fingerprint)`. Kept separate from the
    per-series data query so the unit costs one small grouped scan regardless
    of how many series a query returns."""
    if not metric_names:
        return {}
    names = sorted(metric_names)
    query = parse_select(
        """
            SELECT series_fingerprint, any(unit) AS unit
            FROM posthog.metric_series
            WHERE metric_name IN {names}
            GROUP BY series_fingerprint
        """,
        placeholders={"names": ast.Tuple(exprs=[ast.Constant(value=n) for n in names])},
    )
    response = execute_hogql_query(
        query_type="MetricUnitsLookup",
        query=query,
        team=team,
        workload=Workload.METRICS,
        # Same byte cap as the data queries: without it a high-cardinality name set
        # would make this metadata scan the most expensive read of the request.
        settings=HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
            read_overflow_mode="throw",
        ),
    )
    return {int(row[0]): str(row[1]) for row in (response.results or []) if row[1]}


def _unit_for_fingerprints(fingerprints: set[int], units_by_fingerprint: dict[int, str]) -> str | None:
    """The ingested unit shared by the physical series one output series
    aggregated. The unit only applies when every contributing series carries
    the same one. A disagreement, or a mix of unit and no unit, means the
    merge has no correct single unit, so it returns None. Series that all
    carry no unit return "", which `_output_unit` needs to tell a unitless
    counter (whose rate is still per second) apart from a disagreement."""
    units = {units_by_fingerprint.get(fp, "") for fp in fingerprints}
    if len(units) != 1:
        return None
    (unit,) = units
    return unit


# Prometheus names carry the base unit as a suffix, and a scraped metric has no unit field.
_PROMETHEUS_UNIT_SUFFIXES = (("_seconds", "s"), ("_milliseconds", "ms"), ("_bytes", "By"))


def _prometheus_name_unit(metric_name: str) -> str | None:
    return next((unit for suffix, unit in _PROMETHEUS_UNIT_SUFFIXES if metric_name.endswith(suffix)), None)


def _output_unit(ingested: str | None, clause: MetricQueryClause) -> str | None:
    """The unit of the values a clause returns, which differs from the
    ingested unit when the clause transforms the values. COUNT returns a
    number of series, so it has no unit, even after a range function. RATE
    divides by the bucket length in seconds, so it returns the ingested unit
    per second, as a UCUM string the frontend formatter reads. Every other
    aggregation keeps the ingested unit.

    A histogram quantile of series that all carry no unit reads the unit from
    a Prometheus name suffix: a percentile is in the unit of the observations,
    and `http_request_duration_seconds` observes seconds."""
    if ingested is None or clause.aggregation is MetricAggregation.COUNT:
        return None
    if clause.aggregation is MetricAggregation.RATE or clause.range_function is MetricRangeFunction.RATE:
        return f"{ingested or '1'}/s"
    if not ingested and clause.aggregation is MetricAggregation.HISTOGRAM_QUANTILE:
        return _prometheus_name_unit(clause.metric_name)
    return ingested or None


# Hard cap on series returned per clause; the largest series (by summed
# absolute value) win so the most significant groups survive truncation.
# A clause without an aggregation is capped earlier, in the query, at the same number.
MAX_SERIES_PER_CLAUSE = MAX_RAW_SERIES


def _assemble_series(
    rows: list[dict[str, Any]],
    *,
    clause: MetricQueryClause,
    grid: list[str],
    units_by_fingerprint: dict[int, str],
    zero_fill: bool = True,
    ingested_unit: str | None = None,
) -> list[MetricSeries]:
    """Split bucketed rows into one series per label-set, zero-filled onto
    the shared grid so every series (and later, every clause of a formula)
    has identical timestamps.

    A row with a `series_key` stays apart from rows of another key, even when
    their labels match: two physical series can share a label-set.

    `ingested_unit` sets the unit of a clause whose rows carry no fingerprints, such as a derived metric."""
    by_labels: dict[tuple[tuple[tuple[str, str], ...], int | None], dict[str, float | None]] = {}
    fingerprints_by_labels: dict[tuple[tuple[tuple[str, str], ...], int | None], set[int]] = {}
    bounds_by_labels: dict[tuple[tuple[tuple[str, str], ...], int | None], set[float]] = {}
    layouts_by_labels: dict[tuple[tuple[tuple[str, str], ...], int | None], int] = {}
    for row in rows:
        key = (tuple(sorted(row["labels"].items())), row.get("series_key"))
        by_labels.setdefault(key, {})[row["time"]] = row["value"]
        fingerprints_by_labels.setdefault(key, set()).update(row["series_fingerprints"])
        if "histogram_bounds" in row:
            bounds_by_labels.setdefault(key, set()).update(row["histogram_bounds"])
        if "histogram_layout_count" in row:
            layouts_by_labels[key] = max(layouts_by_labels.get(key, 0), row["histogram_layout_count"])

    # Rank and truncate on the sparse values BEFORE zero-filling, so a
    # high-cardinality group-by never materializes label_sets x grid points
    # only to throw most of them away. Zero-filled points contribute nothing
    # to the magnitude, so the ranking is identical either way.
    ranked = sorted(
        by_labels.items(), key=lambda item: (-sum(abs(v) for v in item[1].values() if v is not None), item[0])
    )
    return [
        MetricSeries(
            labels=dict(key[0]),
            points=tuple(MetricPoint(time=time, value=values.get(time, 0.0 if zero_fill else None)) for time in grid),
            metric_name=clause.metric_name,
            clause=clause.name,
            unit=_output_unit(
                ingested_unit
                if ingested_unit is not None
                else _unit_for_fingerprints(fingerprints_by_labels[key], units_by_fingerprint),
                clause,
            ),
            histogram_bounds=tuple(sorted(bounds_by_labels[key])) if key in bounds_by_labels else None,
            histogram_layout_count=layouts_by_labels.get(key),
        )
        for key, values in ranked[:MAX_SERIES_PER_CLAUSE]
    ]


def _labels_by_fingerprint(team: Team, metric_name: str, fingerprints: set[int]) -> dict[int, dict[str, str]]:
    """The label set of each series, for a clause that returns series unaggregated.

    Resource attributes come first, so a datapoint attribute of the same name wins.
    """
    if not fingerprints:
        return {}
    query = parse_select(
        """
            SELECT series_fingerprint, any(resource_attributes), any(attributes)
            FROM posthog.metric_series
            WHERE metric_name = {metric_name}
              AND series_fingerprint IN {fingerprints}
            GROUP BY series_fingerprint
        """,
        placeholders={
            "metric_name": ast.Constant(value=metric_name),
            "fingerprints": ast.Tuple(exprs=[ast.Constant(value=fp) for fp in sorted(fingerprints)]),
        },
    )
    response = execute_hogql_query(
        query_type="MetricSeriesLabelsLookup",
        query=query,
        team=team,
        workload=Workload.METRICS,
        settings=HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
            read_overflow_mode="throw",
        ),
    )
    return {
        int(row[0]): {str(key): str(value) for key, value in {**(row[1] or {}), **(row[2] or {})}.items() if value}
        for row in (response.results or [])
    }


def _attach_series_labels(team: Team, metric_name: str, rows: list[dict[str, Any]]) -> None:
    """Give each row of an unaggregated clause the labels of its series."""
    labels = _labels_by_fingerprint(team, metric_name, {fp for row in rows for fp in row["series_fingerprints"]})
    for row in rows:
        (fingerprint,) = row["series_fingerprints"]
        row["labels"] = labels.get(int(fingerprint), {})
        row["series_key"] = int(fingerprint)


def _drop_shared_labels(series: list[MetricSeries]) -> list[MetricSeries]:
    """With several series, keep only the labels that tell them apart.

    A label that has the same value on every series only repeats in each legend entry.
    """
    if len(series) < 2:
        return series
    shared = {
        key for key, value in series[0].labels.items() if all(other.labels.get(key) == value for other in series[1:])
    }
    return [replace(s, labels={k: v for k, v in s.labels.items() if k not in shared}) for s in series]


def _resolve_runner_aggregation(clause: MetricQueryClause) -> str | None:
    if clause.aggregation.is_raw:
        return None
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
    node: Any, series_by_clause: dict[str, list[MetricSeries]], grid: list[str]
) -> list[MetricSeries]:
    """Combine clause results point-by-point on the shared grid.

    Series are matched across clauses by exact label-set equality
    (Prometheus-style one-to-one vector matching); a clause that produced a
    single ungrouped series is broadcast to every label-set instead. A
    label-set missing from any non-broadcast clause is dropped.
    """
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
        inputs = {name: grouped[name][label_set] if name in grouped else broadcasts[name] for name in series_by_clause}
        per_clause_points = {name: series.points for name, series in inputs.items()}
        points = tuple(
            MetricPoint(time=time, value=_evaluate_formula_point(node, per_clause_points, index))
            for index, time in enumerate(grid)
        )
        # The formula inherits any mixed-layout estimate it was computed from, so the response still warns about it.
        layout_count = max(
            (s.histogram_layout_count for s in inputs.values() if s.histogram_layout_count is not None), default=None
        )
        result.append(
            MetricSeries(
                labels=dict(label_set),
                points=points,
                metric_name=None,
                clause="formula",
                histogram_layout_count=layout_count,
            )
        )
    return result


def _closing_connection(work: Callable[[], None]) -> None:
    try:
        work()
    finally:
        # The query reads Postgres in the worker thread, and request cleanup only closes the request thread's connection.
        connection.close()


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
    formula_node_checked = (
        parse_formula(request.formula, frozenset(clause.name for clause in request.clauses))
        if request.formula is not None
        else None
    )
    record_metric_queries(team, (clause.metric_name for clause in request.clauses))
    runners: list[tuple[MetricQueryClause, MetricQueryRunner | DerivedMetricQueryRunner, bool]] = []
    derived_units: dict[str, str] = {}
    derived_enabled = any(_is_derived_metric_name(c.metric_name) for c in request.clauses) and derived_metrics_enabled(
        team
    )
    for clause in request.clauses:
        if derived_enabled and _is_derived_metric_name(clause.metric_name):
            derived_runner = DerivedMetricQueryRunner(
                team=team,
                clause=clause,
                date_from=request.date_from,
                date_to=request.date_to,
                interval=request.interval,
            )
            derived_units[clause.name] = derived_runner.unit
            runners.append((clause, derived_runner, False))
            continue
        runner_aggregation = _resolve_runner_aggregation(clause)
        runner = build_metric_query_runner(
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
            range_function=clause.range_function.value if clause.range_function is not None else None,
        )
        runners.append((clause, runner, runner_aggregation is None))
    rows_by_clause: dict[str, list[dict[str, Any]]] = {clause.name: [] for clause in request.clauses}
    units_by_fingerprint: dict[int, str] = {}

    def run_clause(clause: MetricQueryClause, runner: MetricQueryRunner | DerivedMetricQueryRunner, raw: bool) -> None:
        rows = runner.run()
        if raw:
            _attach_series_labels(team, clause.metric_name, rows)
        rows_by_clause[clause.name] = rows

    def load_units() -> None:
        units_by_fingerprint.update(_units_by_fingerprint(team, {clause.metric_name for clause in request.clauses}))

    # The clause queries and the unit lookup do not depend on each other, so a tile waits for the slowest one,
    # not for their sum. A formula combines clauses of different units, so its series carry no unit.
    work: list[Callable[[], None]] = [partial(run_clause, *item) for item in runners]
    if formula_node_checked is None:
        work.append(load_units)
    # Django does not make the test transaction visible to another thread.
    if len(work) <= 1 or settings.IN_UNIT_TESTING:
        for item in work:
            item()
    else:
        run_in_parallel_threads(
            [partial(_closing_connection, item) for item in work], thread_name_prefix="metrics_clauses"
        )

    grid = sorted({row["time"] for rows in rows_by_clause.values() for row in rows})
    if not grid:
        empty_clause = "formula" if formula_node_checked is not None else request.clauses[0].name
        metric_name = None if formula_node_checked is not None else request.clauses[0].metric_name
        return [MetricSeries(labels={}, points=(), metric_name=metric_name, clause=empty_clause)]

    series_by_clause = {
        clause.name: _assemble_series(
            rows_by_clause[clause.name],
            clause=clause,
            grid=grid,
            units_by_fingerprint=units_by_fingerprint,
            zero_fill=request.zero_fill,
            ingested_unit=derived_units.get(clause.name),
        )
        for clause in request.clauses
    }

    if formula_node_checked is not None:
        return _evaluate_formula(formula_node_checked, series_by_clause, grid)

    return [
        series
        for clause in request.clauses
        for series in (
            _drop_shared_labels(series_by_clause[clause.name])
            if clause.aggregation.is_raw
            else series_by_clause[clause.name]
        )
    ]


def list_metric_query_counts(*, team: Team, days: int, limit: int) -> list[MetricQueryCount]:
    """How often queries read each metric of the team in the last `days` UTC days, the most queried first."""
    return _list_metric_query_counts(team, days=days, limit=limit)


def record_promql_query(*, team: Team, expr: str) -> None:
    """Count one query for each metric that a PromQL expression selects. A failed write never raises."""
    _record_promql_query(team, expr)


def run_promql_query(
    *, team: Team, expr: str, date_from: dt.datetime, date_to: dt.datetime, interval: str | None
) -> list[MetricSeries]:
    """Run a PromQL range query on Snuffle. The caller checks the Snuffle feature flag. `date_to` is exclusive."""
    if date_to <= date_from:
        raise ValueError("date_to must be after date_from")
    if date_to - date_from > MAX_QUERY_SPAN:
        raise ValueError(f"date range too wide; the maximum span is {MAX_QUERY_SPAN.days} days")
    with query_concurrency_slots(team):
        series = run_promql_range(team, expr, date_from, date_to, interval)
    return [
        replace(s, points=tuple(p for p in s.points if dt.datetime.fromisoformat(p.time) < date_to)) for s in series
    ]


# An instant builder query reads 5-minute buckets unless told otherwise: every series scraped at least once
# every 5 minutes has a sample in each one, as with PromQL's 5-minute lookback.
DEFAULT_INSTANT_INTERVAL = "minute_5"
# The instant value is the last of a few complete buckets, so a range function sees the buckets before it.
_INSTANT_BUCKETS = 3


def run_promql_instant_query(*, team: Team, expr: str, time: dt.datetime) -> list[MetricSeries]:
    """Run a PromQL instant query on Snuffle at `time`: one point per series. The caller checks the Snuffle flag."""
    with query_concurrency_slots(team):
        return run_promql_instant(team, expr, time)


def run_metric_instant_query(
    *,
    team: Team,
    clauses: tuple[MetricQueryClause, ...],
    time: dt.datetime,
    interval: str | None = None,
    formula: str | None = None,
) -> list[MetricSeries]:
    """The last complete bucket before `time` of a builder query: one point per series.

    The buckets are `interval` wide (5 minutes by default) and end at the bucket boundary at or before `time`,
    so the value is the one the chart shows for that bucket.
    """
    resolved = interval or DEFAULT_INSTANT_INTERVAL
    end = _align_to_interval(time, resolved, tzinfo=team.timezone_info)
    request = MetricQueryRequest(
        clauses=clauses,
        date_from=end - _INSTANT_BUCKETS * _interval_step(resolved),
        date_to=end,
        interval=resolved,
        formula=formula,
    )
    return [replace(s, points=s.points[-1:]) for s in run_metric_query(team=team, request=request)]


def metric_query_concurrency_slots(team: Team) -> AbstractContextManager[None]:
    """Hold the concurrency slots of a metrics query runner around `run_metric_query`.

    Use it when you call `run_metric_query` outside a query runner, so the query counts against the same limits.
    """
    return query_concurrency_slots(team)


def pick_metric_query_interval(*, date_from: dt.datetime, date_to: dt.datetime, max_buckets: int) -> str:
    """The finest `MetricQueryRequest.interval` that keeps the bucket count at or below `max_buckets`."""
    return _pick_interval(date_from, date_to, target_bucket_count=max_buckets)


def list_metric_names(
    *,
    team: Team,
    search: str = "",
    limit: int = 100,
    services: Sequence[str] = (),
    names: Sequence[str] = (),
    match: str = "substring",
    include_sparklines: bool = True,
    include_first_seen: bool = False,
    fold_histograms: bool = False,
) -> list[dict[str, Any]]:
    """List distinct metric names for the team's picker.

    Returns a list of `{"name": str, "metric_type": str, ...}` dicts.
    Passing `services` narrows the list to names those services reported.
    `match` decides how `search` matches a name: a case-insensitive `substring`
    or `prefix`, or an RE2 `regex`. `include_first_seen` adds each name's
    earliest hour within retention, and `fold_histograms` folds a Prometheus
    classic histogram's `_bucket`/`_sum`/`_count` rows into the `_bucket` row.
    Raises `ValueError` for an out-of-range limit, too many services, an
    unknown match mode or an invalid regex.

    The unsearched list is cached per team and service scope for a minute;
    searches are not. Behind the derived series flag, the derived metrics the
    team can query follow the ingested names, within `limit`.
    """
    if names:
        derived_names = [name for name in names if _is_derived_metric_name(name)]
        ingested_names = [name for name in names if not _is_derived_metric_name(name)]
        ingested = (
            MetricNamesQueryRunner(team=team, services=services, names=ingested_names, limit=len(ingested_names)).run()
            if ingested_names
            else []
        )
        if not derived_names or not derived_metrics_enabled(team):
            return ingested
        available = {metric.name for metric in list_derived_metric_names(team)}
        return [*ingested, *(_derived_name_row(get_derived_metric(n)) for n in derived_names if n in available)]
    ingested = cached_metric_names(
        team=team,
        search=search,
        limit=limit,
        services=services,
        match=match,
        include_sparklines=include_sparklines,
        include_first_seen=include_first_seen,
    )
    if fold_histograms:
        ingested = fold_classic_histograms(ingested)
    if not derived_metrics_enabled(team):
        return ingested
    derived = [
        _derived_name_row(metric, include_first_seen=include_first_seen)
        for metric in list_derived_metric_names(team)
        if name_matches(metric.name, search, match)
    ]
    return [*ingested, *derived][:limit]


def _derived_name_row(metric: DerivedMetric, *, include_first_seen: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": metric.name,
        "metric_type": metric.metric_type.value,
        "unit": metric.unit,
        "last_seen": None,
        "sparkline": [],
    }
    if include_first_seen:
        row["first_seen"] = None
    return row


def list_metric_picker_names(
    *,
    team: Team,
    search: str = "",
    limit: int = 100,
    services: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """List current metric names and types for the viewer picker, without sparklines or caching."""
    ingested = MetricNamesQueryRunner(team=team, search=search, limit=limit, services=services).run_picker()
    if not derived_metrics_enabled(team):
        return ingested
    derived: list[dict[str, Any]] = [
        {"name": metric.name, "metric_type": metric.metric_type.value}
        for metric in list_derived_metric_names(team, search=search)
    ]
    return [*ingested, *derived][:limit]


def is_derived_metric_name(name: str) -> bool:
    """True for a name that the query computes from spans and logs instead of reading ingested samples."""
    return _is_derived_metric_name(name)


def get_derived_series_status(team: Team, *, can_read: Callable[[APIScopeObject], bool]) -> DerivedSeriesStatus:
    """Whether the team has spans or logs to derive series from, and whether derived series are on for it.

    `can_read` says whether the caller can read a source's resource (`logs`, `tracing`). A source the
    caller cannot read counts as absent, so the answer does not reveal that the team sends it.
    """
    has_sources = team_has_derived_sources(team, can_read=can_read)
    return DerivedSeriesStatus(has_sources=has_sources, enabled=has_sources and derived_metrics_enabled(team))


def derived_metric_resources(names: Iterable[str]) -> list[APIScopeObject]:
    """The access-control resources (`logs`, `tracing`) that the derived metrics among `names` read.

    A caller that queries these names must also hold read access to each resource.
    """
    return _derived_metric_resources(names)


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
    metric_name: str = "",
    search: str = "",
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List attribute keys by distinct value count, from highest to lowest.

    When a metric name is provided, only series that emitted that metric in the
    recent window supply choices. Datapoint and resource attributes are merged
    into one list (filters run with scope 'auto', so the split doesn't matter
    to callers); `service_name` is always surfaced when it matches the search.
    The window defaults to the last 24 hours. Returns `{"name": str,
    "value_count": int}` dicts. Raises `ValueError` for an out-of-range limit
    or an inverted window.
    """
    runner = MetricAttributeKeysQueryRunner(
        team=team,
        metric_name=metric_name,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return runner.run()


def list_metric_attribute_values(
    *,
    team: Team,
    key: str,
    metric_name: str = "",
    search: str = "",
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List observed values for one metric attribute key, most frequent first,
    for the filter bar's value autocomplete.

    When a metric name is provided, only values seen on that metric supply
    choices. `service_name`/`service.name` read the first-class column,
    matching how filters on it execute. The window defaults to the last 24 hours. Returns
    `{"id": str, "name": str, "count": int}` dicts. Raises `ValueError` for an
    empty key, an out-of-range limit, or an inverted window.
    """
    runner = MetricAttributeValuesQueryRunner(
        team=team,
        key=key,
        metric_name=metric_name,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return runner.run()


def check_metric_variable_regex(regex: str | None) -> None:
    """Raises `ValueError` for a variable regex that the options cannot use."""
    compile_regex(regex)


def list_metric_variable_options(
    *,
    team: Team,
    source: MetricsDashboardVariableSource,
    query: str | None = None,
    custom_values: list[str] | None = None,
    regex: str | None = None,
    variables: Sequence[MetricsDashboardVariable] = (),
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[str]:
    """`variables` are the selections of the other variables, which the query can refer to as `$name`.

    `date_from` and `date_to` are a dashboard date filter, such as `-7d`, and resolve as they do for tiles.
    Raises `ValueError` for a bad query or window, and `ConcurrencyLimitExceeded` when the organization
    runs too many queries.
    """
    # `all` looks up the earliest event, which is a query, so it counts against the same limits.
    lookup = query_concurrency_slots(team) if date_from == "all" else nullcontext()
    try:
        with lookup:
            window = metrics_query_date_range(team, DateRange(date_from=date_from, date_to=date_to))
            resolved_from, resolved_to = window.date_from(), window.date_to()
    except (ValueError, OverflowError) as exc:
        raise ValueError("The window of the variable options is not a valid date range.") from exc
    check_options_window(resolved_from, resolved_to)
    # The caller sends the options that All stands for, so an empty list is a known empty set.
    selections = {
        name: with_values(variable, variable.values) if variable.is_all else variable
        for name, variable in from_dashboard(variables).items()
    }
    return list_variable_options(
        team=team,
        source=source,
        query=query,
        custom_values=custom_values,
        regex=regex,
        variables=selections,
        date_from=resolved_from,
        date_to=resolved_to,
        slot=partial(query_concurrency_slots, team),
    )


def list_metric_event_samples(
    *,
    team: Team,
    metric_name: str | None = None,
    date_from: dt.datetime,
    date_to: dt.datetime,
    trace_id: str | None = None,
    span_id: str | None = None,
    filters: Sequence[MetricFilter] = (),
    metric_type: MetricType | None = None,
    limit: int = 100,
) -> list[MetricEventSample]:
    """List individual metric emissions (the events model), newest first.

    Each sample carries its value, attributes, and trace linkage, so the
    Samples view can render raw rows and pivot to the trace behind any one.
    Pass `trace_id` for the reverse pivot — every emission on a given trace,
    across all metric names when `metric_name` is omitted (the tracing
    product's Metrics tab); `metric_name` or `trace_id` is required. Pass
    `span_id` (with `trace_id`) to narrow to one span's emissions, so the
    result stays exact even when the trace has more emissions than `limit`.
    `filters` and `metric_type` narrow the emissions to the same series a
    `run_metric_query` call with those arguments charts, so a filtered view
    and its chart agree. Both are matched against the emission's series, so
    an emission whose series row hasn't been ingested yet drops out once
    either is set; both require `metric_name`.
    Raises `ValueError` for a missing metric name and trace id, an inverted
    window, an invalid regex filter, or an out-of-range limit; the
    presentation layer surfaces these as 400s.
    """
    runner = MetricEventSamplesQueryRunner(
        team=team,
        metric_name=metric_name,
        date_from=date_from,
        date_to=date_to,
        trace_id=trace_id,
        span_id=span_id,
        filters=filters,
        metric_type=metric_type,
        limit=limit,
    )
    return [MetricEventSample(**row) for row in runner.run()]


# PoC cap: team-wide — Error Tracking spike events carry no service attribution,
# so there is no correlation key to scope them to one metric's service yet.
_ERROR_SPIKES_LIMIT = 200


def list_metric_error_spikes(*, team: Team, date_from: dt.datetime, date_to: dt.datetime) -> list[MetricErrorSpike]:
    """List Error Tracking issue spikes detected in a time window, for the
    metrics chart's error-spike overlay.

    Team-wide: Error Tracking issues carry no service attribution today, so
    this cannot be scoped to the metric's own service yet.
    """
    events = list_latest_spike_events(
        team_id=team.id,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        limit=_ERROR_SPIKES_LIMIT,
    )
    return [
        MetricErrorSpike(
            detected_at=event.detected_at.isoformat(),
            issue_id=str(event.issue.id),
            issue_name=event.issue.name,
        )
        for event in events
    ]


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


def start_dashboard_import(*, team: Team, user: User, request: DashboardImportRequest) -> DashboardImportStatus:
    """Start an import of a Grafana dashboard JSON model or a dashboard screenshot as a new dashboard.

    Converts what it can at once. Starts an agent task for the rest, and then the status has an id to poll.
    Raises `DashboardImportError` with a message for the user.
    """
    from products.metrics.backend.dashboard_import.importer import (  # noqa: PLC0415 — keeps the image and task code off the facade import path
        DashboardImporter,
    )

    return DashboardImporter(team=team, user=user).start(request)


def get_dashboard_import(*, team: Team, user: User, import_id: str) -> DashboardImportStatus | None:
    """The status of the user's import. Builds the dashboard when the agent finished and nothing built it yet."""
    from products.metrics.backend.dashboard_import.importer import (  # noqa: PLC0415 — keeps the image and task code off the facade import path
        DashboardImporter,
    )

    return DashboardImporter(team=team, user=user).status(import_id)


def list_dashboard_imports(*, team: Team, user: User) -> list[DashboardImportStatus]:
    """The user's recent imports that used an agent, newest first, with the progress of the ones that run."""
    from products.metrics.backend.dashboard_import.importer import (  # noqa: PLC0415 — keeps the image and task code off the facade import path
        DashboardImporter,
    )

    return DashboardImporter(team=team, user=user).recent()


def finalize_dashboard_import(*, team_id: int, import_id: str) -> None:
    """Build the dashboard of an import whose agent task ended. Safe to call more than once."""
    from products.metrics.backend.dashboard_import.importer import (  # noqa: PLC0415 — keeps the image and task code off the facade import path
        finalize_import,
    )

    finalize_import(team_id=team_id, task_id=import_id, background=True)


def check_dashboard_import_layout(*, team_id: int, import_id: str, saved_at: dt.datetime | None = None) -> None:
    """Take the agent's latest answer of a screenshot import, and send it a picture of the dashboard or end it."""
    from products.metrics.backend.dashboard_import.importer import (  # noqa: PLC0415 — keeps the image and task code off the facade import path
        check_import_layout,
    )

    check_import_layout(team_id=team_id, task_id=import_id, saved_at=saved_at)


def check_dashboard_panel_queries(
    *, team: Team, user: User, panels: Sequence[PanelQueryCheckRequest], import_id: str | None = None
) -> list[PanelQueryCheckResult]:
    """Check panel queries the way a dashboard import checks them before it builds the dashboard."""
    from products.metrics.backend.dashboard_import.importer import (  # noqa: PLC0415 — keeps the image and task code off the facade import path
        check_panel_queries,
    )

    return check_panel_queries(team=team, user=user, panels=panels, import_id=import_id)


def list_suggested_dashboards(*, team: Team) -> list[SuggestedDashboard]:
    """The approved bank dashboards that suit the metrics of the team, best fit first.

    The first call for a team that was never analyzed starts its analysis, so suggestions appear without
    waiting for its metric names to change.
    """
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        discovery,
        service,
    )
    from products.metrics.backend.temporal.schedule import (  # noqa: PLC0415 — keeps temporalio off the facade import path
        start_team_analysis,
    )

    discovery.record_opened(team.id)
    if discovery.needs_analysis_on_open(team.id):
        try:
            start_team_analysis(team.id, force=True)
        except Exception:
            discovery.forget_analysis_on_open(team.id)
            logger.warning("metrics_suggested_dashboards_first_analysis_not_started", team_id=team.id)
    return service.list_suggestions(team)


def create_suggested_dashboard(*, team: Team, user: User, suggestion_id: str) -> int:
    """Create the dashboard of a suggestion as the user, and return its id. A second call returns the same id.

    Raises `SuggestedDashboardError` with a message for the user.
    """
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.create_from_suggestion(team, user, suggestion_id)


def analyze_team_metrics_now(*, team: Team) -> None:
    """Start an analysis of the team's metric names now, even when nothing changed. For the staff review."""
    from products.metrics.backend.temporal.schedule import (  # noqa: PLC0415 — keeps temporalio off the facade import path
        start_team_analysis,
    )

    start_team_analysis(team.id, force=True)


def list_dashboard_templates(*, status: DashboardTemplateStatus | None = None) -> list[DashboardTemplateSummary]:
    """The templates of the metrics dashboard bank, newest first. Instance-wide, for the staff review."""
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.list_templates(status)


def get_dashboard_template(*, template_id: str) -> DashboardTemplateSummary:
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.get_template(template_id)


def open_dashboard_template_preview(*, team: Team, user: User, template_id: str) -> int:
    """The id of an unlisted dashboard in the team that shows the template with live data. Builds it when needed."""
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.open_preview(team, user, template_id)


def approve_dashboard_template(*, user: User, template_id: str) -> DashboardTemplateSummary:
    """Approve a template. The changes on its preview dashboard become the template first."""
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.approve(user, template_id)


def reject_dashboard_template(*, user: User, template_id: str) -> DashboardTemplateSummary:
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.reject(user, template_id)


def regenerate_dashboard_template(*, user: User, template_id: str) -> DashboardTemplateSummary:
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.regenerate(user, template_id)


def dashboard_template_picture(*, template_id: str, round_number: int) -> bytes | None:
    """The PNG that a generation round rendered of the preview dashboard."""
    from products.metrics.backend.suggested_dashboards import (  # noqa: PLC0415 — keeps the dashboard and export code off the facade import path
        service,
    )

    return service.picture(template_id, round_number)


def list_recording_rules(*, team: Team) -> list[RecordingRule]:
    return recording_rule_logic.list_rules(team.id)


def get_recording_rule(*, team: Team, rule_id: str) -> RecordingRule:
    """Raises `RecordingRuleNotFound`."""
    return recording_rule_logic.get_rule(team.id, rule_id)


def create_recording_rule(
    *, team: Team, user: User, metric_name: str, query: str, description: str, enabled: bool
) -> RecordingRule:
    """Raises `RecordingRuleError` with a message for the user."""
    return recording_rule_logic.create_rule(
        team.id, created_by_id=user.id, metric_name=metric_name, query=query, description=description, enabled=enabled
    )


def update_recording_rule(
    *,
    team: Team,
    rule_id: str,
    query: str | None = None,
    description: str | None = None,
    enabled: bool | None = None,
) -> RecordingRule:
    """Raises `RecordingRuleError` with a message for the user. The metric name cannot change."""
    return recording_rule_logic.update_rule(team.id, rule_id, query=query, description=description, enabled=enabled)


def delete_recording_rule(*, team: Team, rule_id: str) -> None:
    """Raises `RecordingRuleNotFound`."""
    recording_rule_logic.delete_rule(team.id, rule_id)
