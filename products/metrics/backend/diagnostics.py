"""Recompute one chart point from its raw samples, and show the working.

A metrics chart is several reductions deep by the time it reaches a pixel, and
every one of them returns a plausible-looking number when it is wrong. The only
way to know a point is right is to take the bucket apart: which series reported,
what each one sent, what each collapsed to, and how those combined.

`decompose_bucket` does that twice over. It reduces the raw samples in Python
through `fundamentals`, and separately asks `MetricQueryRunner` for the same
point. Two independent paths to one number means a disagreement is visible
rather than inferred — and the per-series breakdown alongside it shows which
step diverged.

The Python side is deliberately not built from the HogQL builders. A reference
that shares its assumptions with the thing it checks agrees with it by
construction and catches nothing.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import replace

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import (
    MetricBucketDecomposition,
    MetricFilter,
    MetricSampleView,
    MetricSeriesBreakdown,
)
from products.metrics.backend.fundamentals import Sample, TemporalReducer, apply_plan, plan_reduction, reduce_temporal
from products.metrics.backend.metric_query_runner import (
    _QUERY_SETTINGS,
    MetricQueryRunner,
    _interval_step,
    counter_lookback,
    filters_expr,
    type_filter_expr,
)

# How much of a bucket the breakdown lists. Totals are computed over everything
# in the bucket; these only bound what gets rendered, and the decomposition says
# so when it has trimmed something.
DEFAULT_MAX_SERIES = 20
DEFAULT_MAX_SAMPLES_PER_SERIES = 12

# A bucket on a wide metric can hold millions of rows. Reading every one to
# explain a single point is not worth the cluster time, so the raw read is
# bounded and reports when it hit the bound.
_MAX_ROWS_READ = 50000


def _as_utc(timestamp: dt.datetime) -> dt.datetime:
    """ClickHouse hands timestamps back naive; the bucket edges are aware."""
    return timestamp.replace(tzinfo=dt.UTC) if timestamp.tzinfo is None else timestamp.astimezone(dt.UTC)


def _raw_samples_query(
    *,
    metric_name: str,
    date_from: dt.datetime,
    bucket_end: dt.datetime,
    filters: Sequence[MetricFilter],
    metric_type: str | None,
) -> ast.SelectQuery:
    query = parse_select(
        """
            SELECT
                service_name,
                attributes,
                resource_attributes,
                metric_type,
                aggregation_temporality,
                timestamp,
                value
            FROM posthog.metrics
            WHERE metric_name = {metric_name}
              AND timestamp >= {date_from}
              AND timestamp < {date_to}
              AND {filters}
              AND {type_filter}
            ORDER BY timestamp ASC
            LIMIT {row_limit}
        """,
        placeholders={
            "metric_name": ast.Constant(value=metric_name),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=bucket_end),
            "filters": filters_expr(filters),
            "type_filter": type_filter_expr(metric_type),
            "row_limit": ast.Constant(value=_MAX_ROWS_READ),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _actual_value(
    *,
    team: Team,
    metric_name: str,
    aggregation: str,
    bucket_start: dt.datetime,
    bucket_end: dt.datetime,
    interval: str,
    filters: Sequence[MetricFilter],
    metric_type: str | None,
    quantile: float | None,
) -> float | None:
    """What the product would plot for this point, through the real runner.

    The runner reaches back past `date_from` on its own for the counter
    functions' predecessor sample, so this asks for exactly the one bucket the
    decomposition is explaining.
    """
    rows = MetricQueryRunner(
        team=team,
        metric_name=metric_name,
        aggregation=aggregation,
        date_from=bucket_start,
        date_to=bucket_end,
        interval=interval,
        filters=filters,
        metric_type=metric_type,
        quantile=quantile,
    ).run()
    for row in rows:
        if _as_utc(dt.datetime.fromisoformat(row["time"])) == bucket_start:
            return row["value"]
    return None


def decompose_bucket(
    *,
    team: Team,
    metric_name: str,
    aggregation: str,
    bucket_start: dt.datetime,
    interval: str,
    filters: Sequence[MetricFilter] = (),
    metric_type: str | None = None,
    quantile: float | None = None,
    max_series: int = DEFAULT_MAX_SERIES,
    max_samples_per_series: int = DEFAULT_MAX_SAMPLES_PER_SERIES,
) -> MetricBucketDecomposition:
    """Take one chart point apart into the series and samples behind it."""
    bucket_start = _as_utc(bucket_start)
    step = _interval_step(interval)
    bucket_end = bucket_start + step
    # The counter functions diff against the newest sample before the bucket,
    # the way the chart's window function does, so their raw read reaches back
    # over exactly the runner's lookback. A shorter reach here would find a
    # different predecessor and report a disagreement the chart does not have.
    needs_boundary = aggregation in ("rate", "increase")
    read_from = bucket_start - counter_lookback(interval) if needs_boundary else bucket_start

    response = execute_hogql_query(
        query_type="MetricBucketDecomposition",
        query=_raw_samples_query(
            metric_name=metric_name,
            date_from=read_from,
            bucket_end=bucket_end,
            filters=filters,
            metric_type=metric_type,
        ),
        team=team,
        workload=Workload.LOGS,
        settings=_QUERY_SETTINGS,
    )
    rows = response.results or []
    rows_truncated = len(rows) >= _MAX_ROWS_READ

    # Group the raw rows into series, keyed the way a series is actually
    # identified: everything that isn't the timestamp or the value.
    grouped: dict[tuple, list[Sample]] = {}
    predecessors: dict[tuple, Sample] = {}
    identities: dict[tuple, tuple[str, dict[str, str], dict[str, str]]] = {}
    resolved_type = metric_type or ""
    temporality = ""
    for service_name, attributes, resource_attributes, row_metric_type, row_temporality, timestamp, value in rows:
        key = (
            service_name,
            tuple(sorted(dict(attributes).items())),
            tuple(sorted(dict(resource_attributes).items())),
            row_metric_type,
        )
        sample = Sample(timestamp=_as_utc(timestamp), value=float(value))
        if sample.timestamp < bucket_start:
            # Only a series' newest pre-bucket reading matters: it is the
            # baseline its first in-bucket diff runs against.
            held = predecessors.get(key)
            if held is None or sample.timestamp > held.timestamp:
                predecessors[key] = sample
        else:
            grouped.setdefault(key, []).append(sample)
        identities.setdefault(key, (service_name, dict(attributes), dict(resource_attributes)))
        # A bucket normally holds one type and one temporality; when a name has
        # been ingested as several, the first is enough to plan a reduction and
        # the type check reports the blend separately.
        resolved_type = resolved_type or row_metric_type
        temporality = temporality or row_temporality

    plan = plan_reduction(
        aggregation=aggregation,
        metric_type=resolved_type,
        temporality=temporality,
        interval_seconds=step.total_seconds(),
    )
    if quantile is not None:
        plan = replace(plan, quantile=quantile)

    # Delta increments before the bucket belong to the previous point, so only
    # the odometer-style reduction gets its baseline prepended.
    if plan.temporal is TemporalReducer.INCREASE:
        reduction_input = {
            key: ([predecessors[key], *samples] if key in predecessors else samples) for key, samples in grouped.items()
        }
    else:
        reduction_input = grouped

    reference_value = apply_plan(reduction_input, plan)

    # Largest contributors first — that is what someone reading a surprising
    # total wants to see, and it makes the trimmed tail the least interesting part.
    ordered_keys = sorted(grouped, key=lambda key: (-len(grouped[key]), identities[key][0]))
    breakdown: list[MetricSeriesBreakdown] = []
    for key in ordered_keys[:max_series]:
        samples = grouped[key]
        service_name, labels, resource_labels = identities[key]
        if plan.temporal is TemporalReducer.POOLED_SAMPLES:
            series_value = None
        else:
            # Normalized the same way as the bucket's total, so the series
            # a reader adds up still reach the number they are explaining.
            reduced = reduce_temporal(reduction_input[key], plan.temporal)
            series_value = None if reduced is None else reduced / plan.divisor
        breakdown.append(
            MetricSeriesBreakdown(
                service_name=service_name,
                labels=labels,
                resource_labels=resource_labels,
                samples=tuple(
                    MetricSampleView(time=sample.timestamp.isoformat(), value=sample.value)
                    for sample in samples[:max_samples_per_series]
                ),
                sample_count=len(samples),
                samples_truncated=len(samples) > max_samples_per_series,
                value=series_value,
            )
        )

    actual_value = _actual_value(
        team=team,
        metric_name=metric_name,
        aggregation=aggregation,
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        interval=interval,
        filters=filters,
        metric_type=metric_type,
        quantile=quantile,
    )

    return MetricBucketDecomposition(
        metric_name=metric_name,
        metric_type=resolved_type,
        temporality=temporality,
        aggregation=aggregation,
        bucket_start=bucket_start.isoformat(),
        interval=interval,
        temporal_reducer=plan.temporal.value,
        spatial_reducer=plan.spatial.value,
        series=tuple(breakdown),
        series_count=len(grouped),
        sample_count=sum(len(samples) for samples in grouped.values()),
        series_truncated=len(grouped) > max_series,
        rows_truncated=rows_truncated,
        reference_value=reference_value,
        actual_value=actual_value,
        # A truncated read means the reference covers only part of the bucket,
        # so any verdict would be an artifact of the unequal inputs.
        agrees=None if rows_truncated else _agrees(reference_value, actual_value),
    )


def _agrees(reference: float | None, actual: float | None) -> bool:
    """Float reductions in ClickHouse and Python accumulate in different orders,
    so exact equality would report noise as disagreement. The tolerance is far
    tighter than any real reduction bug, which move totals by whole multiples."""
    if reference is None or actual is None:
        return reference is None and actual is None
    scale = max(abs(reference), abs(actual), 1.0)
    return abs(reference - actual) <= 1e-9 * scale
