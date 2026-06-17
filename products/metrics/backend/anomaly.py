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
from products.metrics.backend.metric_query_runner import MetricQueryRunner, _pick_interval

# How many label keys to drill into and how many movers to report.
MAX_CANDIDATE_KEYS = 4
MAX_TOP_MOVERS = 8

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


def _find_onset(
    points: list[MetricPoint], anomaly_from_iso: str, baseline_mean: float, baseline_stddev: float, direction: str
) -> str | None:
    threshold = max(
        ONSET_STDDEV_THRESHOLD * baseline_stddev,
        ONSET_RELATIVE_FLOOR * abs(baseline_mean),
        1e-9,
    )
    for point in points:
        if point.time < anomaly_from_iso:
            continue
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
    if anomaly_to <= anomaly_from:
        raise ValueError("anomaly_to must be after anomaly_from")
    if baseline_to is None:
        baseline_to = anomaly_from
    if baseline_from is None:
        baseline_from = baseline_to - (anomaly_to - anomaly_from)
    if baseline_to > anomaly_from:
        raise ValueError("the baseline window must end at or before anomaly_from")

    if aggregation is None:
        aggregation, default_quantile = _default_aggregation(team, metric_name)
        quantile = quantile if quantile is not None else default_quantile
    if aggregation == "histogram_quantile" and quantile is None:
        quantile = 0.95

    # One query over the combined window keeps baseline and anomaly on a
    # single grid; the interval comes from the combined span.
    interval = _pick_interval(baseline_from, anomaly_to)
    anomaly_from_iso = anomaly_from.isoformat()

    def _run(group_by: tuple[MetricGroupBy, ...] = ()) -> list[dict[str, Any]]:
        return MetricQueryRunner(
            team=team,
            metric_name=metric_name,
            aggregation=aggregation,
            date_from=baseline_from,
            date_to=anomaly_to,
            filters=filters,
            group_by=group_by,
            interval=interval,
            quantile=quantile if aggregation == "histogram_quantile" else None,
        ).run()

    rows = _run()
    points = [MetricPoint(time=row["time"], value=row["value"]) for row in rows]
    baseline_values = [p.value for p in points if p.time < anomaly_from_iso]
    anomaly_values = [p.value for p in points if p.time >= anomaly_from_iso]

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
        None
        if direction == "flat"
        else _find_onset(points, anomaly_from_iso, baseline_mean, baseline_stddev, direction)
    )

    movers = _find_top_movers(
        run=_run,
        team=team,
        metric_name=metric_name,
        anomaly_from_iso=anomaly_from_iso,
        anomaly_from=anomaly_from,
        anomaly_to=anomaly_to,
        filters=filters,
        candidate_keys=candidate_keys,
    )

    return MetricAnomalyReport(
        metric_name=metric_name,
        aggregation=aggregation,
        interval=interval,
        baseline_from=baseline_from.isoformat(),
        baseline_to=baseline_to.isoformat(),
        anomaly_from=anomaly_from_iso,
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
    service_name always considered (it's a first-class column duplicated
    into the labels)."""
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
    keys = [row[0] for row in response.results]
    if "service_name" not in keys:
        keys = ["service_name", *keys][:MAX_CANDIDATE_KEYS]
    return tuple(keys)


def _find_top_movers(
    *,
    run: Callable[..., list[dict[str, Any]]],
    team: Team,
    metric_name: str,
    anomaly_from_iso: str,
    anomaly_from: dt.datetime,
    anomaly_to: dt.datetime,
    filters: tuple[MetricFilter, ...],
    candidate_keys: tuple[str, ...] | None,
) -> tuple[MetricAnomalyDimension, ...]:
    keys = candidate_keys or _discover_candidate_keys(team, metric_name, anomaly_from, anomaly_to)

    movers: list[MetricAnomalyDimension] = []
    for key in keys[:MAX_CANDIDATE_KEYS]:
        rows = run(group_by=(MetricGroupBy(key=key),))
        per_label: dict[str, dict[str, list[float]]] = {}
        for row in rows:
            label = row["labels"].get(key, "")
            bucket = "anomaly" if row["time"] >= anomaly_from_iso else "baseline"
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

    def _magnitude(mover: MetricAnomalyDimension) -> float:
        if mover.baseline_value == 0 or mover.change_ratio <= 0:
            return abs(mover.anomaly_value - mover.baseline_value)
        return abs(math.log(mover.change_ratio)) * max(abs(mover.anomaly_value), abs(mover.baseline_value))

    movers.sort(key=lambda m: (-_magnitude(m), m.key, m.label))
    return tuple(movers[:MAX_TOP_MOVERS])
