"""Anomaly characterization for one metric.

Given an anomaly window (and an optional explicit baseline window), this
compares the windows statistically, finds the onset bucket, and drills into
candidate label keys to find which label values moved — the "what changed,
when, and where" an on-call investigator (or agent) needs before
correlating into logs and traces.
"""

from __future__ import annotations

import math
import datetime as dt
import statistics
from collections.abc import Callable
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import (
    MetricAnomalyDimension,
    MetricAnomalyReport,
    MetricFilter,
    MetricGroupBy,
    MetricPoint,
    MetricSeries,
)
from products.metrics.backend.metric_names_query_runner import MetricNamesQueryRunner
from products.metrics.backend.metric_query_runner import (
    _INTERVAL_LADDER,
    _ROW_LIMIT,
    MetricQueryRunner,
    _pick_interval,
    attribute_field,
)

# How many label keys to drill into and how many movers to report.
MAX_CANDIDATE_KEYS = 4
MAX_TOP_MOVERS = 8

# Cap on distinct label values pulled per key in a drill-down. A grouped
# query returns `buckets × cardinality` rows, so a high-cardinality key (pod
# name, request id) would overrun the runner's row limit. We keep the most
# frequent values — enough to surface the dominant cause — and coarsen the
# interval on top of that so the grouped query stays under the budget.
_MAX_DRILLDOWN_LABELS = 50

# Bucket budget for the single combined baseline+anomaly query — the
# resolution follows the anomaly window, but a faraway baseline must not
# blow the runner's row limit.
_MAX_COMBINED_BUCKETS = 2000

# Onset = first anomaly-window bucket beyond this many baseline stddevs
# (with a relative-change floor for near-constant baselines).
ONSET_STDDEV_THRESHOLD = 3.0
ONSET_RELATIVE_FLOOR = 0.5

_AGGREGATION_BY_TYPE = {
    "sum": "rate",
    "gauge": "avg",
    "histogram": "histogram_quantile",
    "exponential_histogram": "p95",
    "summary": "avg",
}


def _default_aggregation(team: Team, metric_name: str) -> tuple[str, float | None]:
    """Pick an aggregation from the metric's OTel type: counters get `rate`,
    gauges `avg`, histograms `histogram_quantile(0.95)`."""
    for row in MetricNamesQueryRunner(team=team, search=metric_name, limit=5).run():
        if row["name"] == metric_name:
            aggregation = _AGGREGATION_BY_TYPE.get(row["metric_type"], "avg")
            return aggregation, 0.95 if aggregation == "histogram_quantile" else None
    return "avg", None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ensure_aware(value: dt.datetime) -> dt.datetime:
    """Naive datetimes are taken as UTC so window comparisons always have a
    timezone to compare on."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def _parse_point_time(value: str) -> dt.datetime:
    """Bucket times come back from HogQL rendered in the *project* timezone,
    so they must be compared as datetimes — ISO strings with different UTC
    offsets do not sort chronologically."""
    return _ensure_aware(dt.datetime.fromisoformat(value))


def _pick_combined_interval(baseline_from: dt.datetime, anomaly_from: dt.datetime, anomaly_to: dt.datetime) -> str:
    """Resolution follows the anomaly window (so a short window keeps fine
    buckets even with a faraway baseline); the combined span only coarsens
    it when it would exceed the bucket budget."""
    interval = _pick_interval(anomaly_from, anomaly_to)
    combined_span = anomaly_to - baseline_from
    index = next(i for i, (name, _, _) in enumerate(_INTERVAL_LADDER) if name == interval)
    while index < len(_INTERVAL_LADDER) - 1 and combined_span / _INTERVAL_LADDER[index][1] > _MAX_COMBINED_BUCKETS:
        index += 1
    return _INTERVAL_LADDER[index][0]


def _find_onset(
    points: list[MetricPoint], anomaly_from: dt.datetime, baseline_mean: float, baseline_stddev: float, direction: str
) -> str | None:
    threshold = max(
        ONSET_STDDEV_THRESHOLD * baseline_stddev,
        ONSET_RELATIVE_FLOOR * abs(baseline_mean),
        1e-9,
    )
    for point in points:
        if _parse_point_time(point.time) < anomaly_from:
            continue
        if point.value is None:
            continue  # non-representable aggregate — can't evidence an onset
        deviation = point.value - baseline_mean
        if direction == "down":
            deviation = -deviation
        if deviation > threshold:
            return point.time
    return None


def characterize_anomaly(
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
    anomaly_from = _ensure_aware(anomaly_from)
    anomaly_to = _ensure_aware(anomaly_to)
    if anomaly_to <= anomaly_from:
        raise ValueError("anomaly_to must be after anomaly_from")
    if baseline_to is None:
        baseline_to = anomaly_from
    if baseline_from is None:
        baseline_from = baseline_to - (anomaly_to - anomaly_from)
    baseline_from = _ensure_aware(baseline_from)
    baseline_to = _ensure_aware(baseline_to)
    if baseline_to > anomaly_from:
        raise ValueError("the baseline window must end at or before anomaly_from")
    if baseline_to <= baseline_from:
        raise ValueError("baseline_to must be after baseline_from")

    if aggregation is None:
        aggregation, default_quantile = _default_aggregation(team, metric_name)
        quantile = quantile if quantile is not None else default_quantile
    if aggregation == "histogram_quantile" and quantile is None:
        quantile = 0.95

    # One query over the combined window keeps baseline and anomaly on a
    # single grid. Buckets between baseline_to and anomaly_from (the gap, for
    # an explicit faraway baseline) are plotted but excluded from the stats.
    interval = _pick_combined_interval(baseline_from, anomaly_from, anomaly_to)

    def _run(
        group_by: tuple[MetricGroupBy, ...] = (),
        interval_override: str | None = None,
        label_allowlist: dict[str, tuple[str, ...]] | None = None,
    ) -> list[dict[str, Any]]:
        return MetricQueryRunner(
            team=team,
            metric_name=metric_name,
            aggregation=aggregation,
            date_from=baseline_from,
            date_to=anomaly_to,
            filters=filters,
            group_by=group_by,
            interval=interval_override or interval,
            quantile=quantile if aggregation == "histogram_quantile" else None,
            group_by_value_allowlist=label_allowlist,
        ).run()

    rows = _run()
    points = [MetricPoint(time=row["time"], value=row["value"]) for row in rows]
    point_times = [_parse_point_time(p.time) for p in points]
    baseline_values = [
        p.value for p, t in zip(points, point_times) if baseline_from <= t < baseline_to and p.value is not None
    ]
    anomaly_values = [p.value for p, t in zip(points, point_times) if t >= anomaly_from and p.value is not None]

    baseline_mean = _mean(baseline_values)
    baseline_stddev = statistics.pstdev(baseline_values) if len(baseline_values) > 1 else 0.0
    anomaly_mean = _mean(anomaly_values)
    anomaly_peak = max(anomaly_values, default=0.0)
    change_ratio = anomaly_mean / baseline_mean if baseline_mean else anomaly_mean

    if math.isclose(anomaly_mean, baseline_mean, rel_tol=0.05, abs_tol=1e-12):
        direction = "flat"
    else:
        direction = "up" if anomaly_mean > baseline_mean else "down"

    onset_time = (
        None if direction == "flat" else _find_onset(points, anomaly_from, baseline_mean, baseline_stddev, direction)
    )

    movers = _find_top_movers(
        run=_run,
        team=team,
        metric_name=metric_name,
        baseline_from=baseline_from,
        baseline_to=baseline_to,
        anomaly_from=anomaly_from,
        anomaly_to=anomaly_to,
        interval=interval,
        filters=filters,
        candidate_keys=candidate_keys,
    )

    return MetricAnomalyReport(
        metric_name=metric_name,
        aggregation=aggregation,
        interval=interval,
        baseline_from=baseline_from.isoformat(),
        baseline_to=baseline_to.isoformat(),
        anomaly_from=anomaly_from.isoformat(),
        anomaly_to=anomaly_to.isoformat(),
        baseline_mean=baseline_mean,
        baseline_stddev=baseline_stddev,
        anomaly_mean=anomaly_mean,
        anomaly_peak=anomaly_peak,
        change_ratio=change_ratio,
        direction=direction,
        onset_time=onset_time,
        top_movers=movers,
        series=MetricSeries(labels={}, points=tuple(points), metric_name=metric_name, clause="anomaly"),
    )


def _discover_candidate_keys(
    team: Team, metric_name: str, date_from: dt.datetime, date_to: dt.datetime
) -> tuple[str, ...]:
    """Most common attribute keys on the metric's rows in the window, with
    service_name always considered (`attribute_field` resolves it to the
    first-class column). The dotted `service.name` resource attribute is
    normalized to `service_name` so the same key isn't drilled twice."""
    query = parse_select(
        """
            SELECT key, count() AS occurrences
            FROM (
                SELECT arrayJoin(arrayConcat(mapKeys(attributes), mapKeys(resource_attributes))) AS key
                FROM posthog.metrics
                WHERE metric_name = {metric_name}
                  AND timestamp >= {date_from}
                  AND timestamp < {date_to}
            )
            GROUP BY key
            ORDER BY occurrences DESC
            LIMIT {limit}
        """,
        placeholders={
            "metric_name": ast.Constant(value=metric_name),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "limit": ast.Constant(value=MAX_CANDIDATE_KEYS),
        },
    )
    response = execute_hogql_query(query_type="MetricQuery", query=query, team=team, workload=Workload.LOGS)
    keys: list[str] = []
    for row in response.results:
        key = "service_name" if row[0] == "service.name" else row[0]
        if key not in keys:
            keys.append(key)
    if "service_name" not in keys:
        keys = ["service_name", *keys]
    return tuple(keys[:MAX_CANDIDATE_KEYS])


def _discover_key_labels(
    team: Team, metric_name: str, key: str, date_from: dt.datetime, date_to: dt.datetime, limit: int
) -> tuple[str, ...]:
    """The most frequent label values for `key` over the window, most common
    first. Resolved through the same field accessor a group_by uses, so the
    first-class service-name column and the attribute maps match the rows the
    drill-down itself groups. The `LIMIT` bounds the returned cardinality, so
    the grouped drill-down can stay under the runner's row budget."""
    label_expr = ast.Call(name="toString", args=[attribute_field(key)])
    query = parse_select(
        """
            SELECT {label} AS label, count() AS occurrences
            FROM posthog.metrics
            WHERE metric_name = {metric_name}
              AND timestamp >= {date_from}
              AND timestamp < {date_to}
            GROUP BY label
            ORDER BY occurrences DESC, label ASC
            LIMIT {limit}
        """,
        placeholders={
            "label": label_expr,
            "metric_name": ast.Constant(value=metric_name),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "limit": ast.Constant(value=limit),
        },
    )
    response = execute_hogql_query(query_type="MetricQuery", query=query, team=team, workload=Workload.LOGS)
    return tuple(row[0] for row in response.results)


def _coarsen_for_cardinality(interval: str, combined_span: dt.timedelta, cardinality: int) -> str:
    """Coarsen `interval` until `buckets × cardinality` fits the row budget,
    giving a grouped drill-down the same protection the ungrouped query has.

    Two buckets of headroom below the limit absorb the partial bucket
    `toStartOfInterval` can add at each window edge and the `>=` truncation
    check, so the grouped query lands strictly under `_ROW_LIMIT`."""
    max_buckets = max(1, _ROW_LIMIT // max(cardinality, 1) - 2)
    index = next(i for i, (name, _, _) in enumerate(_INTERVAL_LADDER) if name == interval)
    while index < len(_INTERVAL_LADDER) - 1 and combined_span / _INTERVAL_LADDER[index][1] > max_buckets:
        index += 1
    return _INTERVAL_LADDER[index][0]


def dimension_magnitude(mover: MetricAnomalyDimension) -> float:
    """How much a label value actually moved, blending relative change with
    scale: a tiny series that tripled and a large series that barely budged
    should not rank — nor be judged the dominant cause — on ratio alone. The
    blast-radius classifier must compare movers on this same measure they were
    ranked by, or the top mover by magnitude can lose a raw-ratio comparison.
    """
    if mover.baseline_value == 0 or mover.change_ratio <= 0:
        return abs(mover.anomaly_value - mover.baseline_value)
    return abs(math.log(mover.change_ratio)) * max(abs(mover.anomaly_value), abs(mover.baseline_value))


def _find_top_movers(
    *,
    run: Callable[..., list[dict[str, Any]]],
    team: Team,
    metric_name: str,
    baseline_from: dt.datetime,
    baseline_to: dt.datetime,
    anomaly_from: dt.datetime,
    anomaly_to: dt.datetime,
    interval: str,
    filters: tuple[MetricFilter, ...],
    candidate_keys: tuple[str, ...] | None,
) -> tuple[MetricAnomalyDimension, ...]:
    keys = candidate_keys or _discover_candidate_keys(team, metric_name, anomaly_from, anomaly_to)

    movers: list[MetricAnomalyDimension] = []
    for key in keys[:MAX_CANDIDATE_KEYS]:
        # Restrict the grouped query to the most frequent label values and
        # coarsen the interval to match, so `buckets × cardinality` stays
        # under the row limit even when the key is high-cardinality.
        labels = _discover_key_labels(team, metric_name, key, baseline_from, anomaly_to, _MAX_DRILLDOWN_LABELS)
        if not labels:
            continue
        drill_interval = _coarsen_for_cardinality(interval, anomaly_to - baseline_from, len(labels))
        rows = run(
            group_by=(MetricGroupBy(key=key),),
            interval_override=drill_interval,
            label_allowlist={key: labels},
        )
        per_label: dict[str, dict[str, list[float]]] = {}
        for row in rows:
            time = _parse_point_time(row["time"])
            if time >= anomaly_from:
                bucket = "anomaly"
            elif baseline_from <= time < baseline_to:
                bucket = "baseline"
            else:
                continue  # gap between an explicit baseline and the anomaly
            label = row["labels"].get(key, "")
            if row["value"] is None:
                continue  # non-representable aggregate (overflow) — not evidence for either window
            per_label.setdefault(label, {"baseline": [], "anomaly": []})[bucket].append(row["value"])
        for label, windows in per_label.items():
            baseline_value = _mean(windows["baseline"])
            anomaly_value = _mean(windows["anomaly"])
            if math.isclose(baseline_value, anomaly_value, rel_tol=0.05, abs_tol=1e-12):
                continue
            ratio = anomaly_value / baseline_value if baseline_value else anomaly_value
            movers.append(
                MetricAnomalyDimension(
                    key=key,
                    label=label,
                    baseline_value=baseline_value,
                    anomaly_value=anomaly_value,
                    change_ratio=ratio,
                )
            )

    movers.sort(key=lambda m: (-dimension_magnitude(m), m.key, m.label))
    return tuple(movers[:MAX_TOP_MOVERS])
