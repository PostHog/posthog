"""Prometheus metrics for the logs volume tick."""

import typing
import datetime as dt

from posthog.temporal.common.metrics import get_metric_meter

# Consumed by `posthog/temporal/common/worker.py` to override Prometheus default
# buckets per-metric. Keep in sync with the histograms emitted below.
LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_METRICS = ("logs_volume_tick_clickhouse_duration_ms",)

LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_BUCKETS = [
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
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
