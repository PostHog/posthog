"""Prometheus metrics for the logs volume tick."""

import typing
import datetime as dt

from posthog.temporal.common.metrics import get_metric_meter

from products.logs.backend.temporal.volume_tick.aggregation import RollupPreview

# Consumed by `posthog/temporal/common/worker.py` to override Prometheus default
# buckets per-metric. Keep in sync with the histograms emitted below.
LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_METRICS = (
    "logs_volume_tick_clickhouse_duration_ms",
    "logs_volume_tick_rollup_duration_ms",
)

# Dense between 750ms and 3s because the discovery query lives there, and again
# between 3s and 7.5s because the rollup query does. Coarser steps put every
# sample in one bucket, so the high quantiles interpolate to a bucket edge and
# report a boundary rather than a latency.
LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_BUCKETS = [
    50.0,
    100.0,
    250.0,
    500.0,
    750.0,
    1_000.0,
    1_500.0,
    2_000.0,
    2_500.0,
    3_000.0,
    4_000.0,
    5_000.0,
    7_500.0,
    10_000.0,
    30_000.0,
    60_000.0,
]

TickOutcome = typing.Literal["ok", "error"]


def increment_tick_runs(outcome: TickOutcome) -> None:
    meter = get_metric_meter({"outcome": outcome})
    counter = meter.create_counter("logs_volume_tick_runs_total", "Volume tick activity runs by outcome")
    counter.add(1)


def record_teams_with_logs(count: int) -> None:
    meter = get_metric_meter()
    gauge = meter.create_gauge(
        "logs_volume_tick_teams_with_logs",
        "Teams that produced log records inside the tick's discovery window",
    )
    gauge.set(count)


def record_clickhouse_duration(duration_ms: int) -> None:
    meter = get_metric_meter()
    hist = meter.create_histogram_timedelta(
        name="logs_volume_tick_clickhouse_duration_ms",
        description="Duration of the tick's ClickHouse discovery query",
        unit="ms",
    )
    hist.record(dt.timedelta(milliseconds=duration_ms))


def record_rollup_duration(duration_ms: int) -> None:
    meter = get_metric_meter()
    hist = meter.create_histogram_timedelta(
        name="logs_volume_tick_rollup_duration_ms",
        description="Duration of the tick's ClickHouse rollup query",
        unit="ms",
    )
    hist.record(dt.timedelta(milliseconds=duration_ms))


def record_rollup_preview(preview: RollupPreview) -> None:
    """Publish what the rollup would write for one due bucket.

    Gauges, not counters: each is a property of the bucket the tick just measured,
    not a running total. `rollup_rows` against `source_rows` is the compression the
    rollup buys; the `missing_dimension` pair is whether its dimensions resolve at all.
    """
    meter = get_metric_meter()
    meter.create_gauge(
        "logs_volume_tick_rollup_rows",
        "Rows the rollup would write for the due bucket",
    ).set(preview.rollup_rows)
    meter.create_gauge(
        "logs_volume_tick_source_rows",
        "Raw log records the due bucket's rollup rows summarize",
    ).set(preview.source_rows)
    meter.create_gauge(
        "logs_volume_tick_distinct_services",
        "Distinct services in the due bucket",
    ).set(preview.distinct_services)
    for dimension, count in (
        ("namespace", preview.rows_without_namespace),
        ("environment", preview.rows_without_environment),
    ):
        get_metric_meter({"dimension": dimension}).create_gauge(
            "logs_volume_tick_rows_missing_dimension",
            "Rollup rows whose dimension resolved to the empty string",
        ).set(count)
