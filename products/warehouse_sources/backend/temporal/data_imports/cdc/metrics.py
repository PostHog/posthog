"""CDC Temporal metrics.

Factory functions over the temporalio activity metric meter, mirroring
`pipeline_v3/metrics.py`. Both the extraction and the orphan-slot sweeper run as
activities, so `activity.metric_meter()` is the right meter for either.

Counters and gauges carry team_id/source_id. Histograms carry neither: every label value
multiplies their buckets, once per worker pod. Sweeper-wide metrics carry no per-source attributes.

The meter keeps a gauge's last value on the pod that set it until the pod restarts, and each run
of a source can land on another pod. So every per-source gauge is set together with an
`*_observed_at_seconds` gauge holding the Unix time it was set, which lets a query keep only the
newest observation per source.

CDC activity bodies are also unit-tested by direct instantiation, outside any
activity context, where `activity.metric_meter()` raises. `_meter()` falls back to
the no-op meter there so instrumented code stays safe to call from anywhere.
"""

from __future__ import annotations

import time

from temporalio import activity
from temporalio.common import MetricCounter, MetricHistogramFloat, MetricMeter


def _meter() -> MetricMeter:
    return activity.metric_meter() if activity.in_activity() else MetricMeter.noop


def _source_meter(team_id: int, source_id: str) -> MetricMeter:
    return _meter().with_additional_attributes({"team_id": str(team_id), "source_id": source_id})


def _set_observed(meter: MetricMeter, name: str, values: dict[str, tuple[str, str, int]]) -> None:
    # Values first: a scrape between the two sees new values under the old stamp, never the reverse.
    for metric_name, (description, unit, value) in values.items():
        meter.create_gauge(metric_name, description, unit).set(value)
    meter.create_gauge(f"{name}_observed_at_seconds", f"Unix time {name} was last set", "s").set(int(time.time()))


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def get_events_extracted_metric(team_id: int, source_id: str) -> MetricCounter:
    return _source_meter(team_id, source_id).create_counter(
        "cdc_events_extracted_total", "Total WAL change events extracted"
    )


def get_micro_batches_flushed_metric(team_id: int, source_id: str) -> MetricCounter:
    return _source_meter(team_id, source_id).create_counter(
        "cdc_micro_batches_flushed_total", "Total mid-run micro-batches flushed"
    )


# Every buffer write is authoritative delivery. The label keeps the value dashboards already filter on.
_BUFFER_LANE_LABEL = {"lane": "ingress"}


def get_buffer_files_written_metric(team_id: int, source_id: str) -> MetricCounter:
    return (
        _source_meter(team_id, source_id)
        .with_additional_attributes(_BUFFER_LANE_LABEL)
        .create_counter("cdc_buffer_files_written_total", "Total buffer files written, by lane")
    )


def get_extract_retry_metric(team_id: int, source_id: str) -> MetricCounter:
    """Extraction runs that are not the first attempt.

    Exposure proxy for the zombie-attempt collision: a superseded attempt that is still alive can
    overwrite a live attempt's buffer file over the same position range with fewer rows, and that
    loss has no detector of its own. It takes a retry to reach, so a quiet counter bounds the risk.
    """
    return _source_meter(team_id, source_id).create_counter(
        "cdc_extract_retried_attempts_total", "Extraction runs starting at attempt > 1"
    )


def get_buffer_write_duration_metric() -> MetricHistogramFloat:
    return (
        _meter()
        .with_additional_attributes(_BUFFER_LANE_LABEL)
        .create_histogram_float("cdc_buffer_write_duration_seconds", "Duration of buffer S3 writes, by lane", "s")
    )


def get_extraction_duration_metric(status: str) -> MetricHistogramFloat:
    return (
        _meter()
        .with_additional_attributes({"status": status})
        .create_histogram_float("cdc_extraction_duration_seconds", "Duration of CDC extraction runs", "s")
    )


def get_extraction_runs_metric(team_id: int, source_id: str, status: str) -> MetricCounter:
    return (
        _source_meter(team_id, source_id)
        .with_additional_attributes({"status": status})
        .create_counter("cdc_extraction_runs_total", "CDC extraction runs, by final status")
    )


def get_slot_advance_metric(team_id: int, source_id: str) -> MetricCounter:
    return _source_meter(team_id, source_id).create_counter("cdc_slot_advance_total", "Total replication slot advances")


def get_slot_advance_failures_metric(team_id: int, source_id: str) -> MetricCounter:
    return _source_meter(team_id, source_id).create_counter(
        "cdc_slot_advance_failures_total", "Total replication slot advance failures"
    )


def record_wal_lag(team_id: int, source_id: str, behind_bytes: int) -> None:
    _set_observed(
        _source_meter(team_id, source_id),
        "cdc_wal_lag",
        {"cdc_wal_lag_bytes": ("Replication slot WAL lag", "By", behind_bytes)},
    )


def record_buffer_backlog(
    team_id: int, source_id: str, *, files: int, size_bytes: int, oldest_age_seconds: int
) -> None:
    """Change files the source's streaming tables have not loaded yet. Zeroes when the buffer is empty."""
    _set_observed(
        _source_meter(team_id, source_id),
        "cdc_buffer_backlog",
        {
            "cdc_buffer_backlog_files": ("Buffer files waiting to load", "", files),
            "cdc_buffer_backlog_bytes": ("Bytes of buffer files waiting to load", "By", size_bytes),
            "cdc_buffer_backlog_oldest_age_seconds": (
                "Age of the oldest buffer file waiting to load",
                "s",
                oldest_age_seconds,
            ),
        },
    )


def get_auto_drop_metric(team_id: int, source_id: str) -> MetricCounter:
    return _source_meter(team_id, source_id).create_counter(
        "cdc_auto_drop_total", "Total slots auto-dropped by the critical-lag safety net"
    )


def get_sweeper_sources_checked_metric() -> MetricCounter:
    return _meter().create_counter("cdc_sweeper_sources_checked_total", "Total CDC sources checked by the sweeper")


def get_sweeper_source_errors_metric() -> MetricCounter:
    return _meter().create_counter("cdc_sweeper_source_errors_total", "Total per-source errors during the sweep")


def get_sweeper_duration_metric() -> MetricHistogramFloat:
    return _meter().create_histogram_float("cdc_sweeper_duration_seconds", "Duration of the orphan-slot sweep", "s")


def record_sweep_started(*, sources_total: int, timeout_seconds: int) -> None:
    """Gauges that identify the sweep in progress. Sweeps land on any pod, so a query takes the pod
    with the newest `cdc_sweeper_started_at_seconds`. A sweep that times out never sets
    `cdc_sweeper_completed_at_seconds`, and its progress gauges stay below the total.
    """
    meter = _meter()
    meter.create_gauge("cdc_sweeper_sources_total", "CDC sources the sweep has to check").set(sources_total)
    meter.create_gauge("cdc_sweeper_timeout_seconds", "Time limit of the sweep", "s").set(timeout_seconds)
    meter.create_gauge("cdc_sweeper_started_at_seconds", "Unix time the sweep started", "s").set(int(time.time()))


def record_sweep_progress(*, processed: int, errored: int) -> None:
    meter = _meter()
    meter.create_gauge("cdc_sweeper_sources_processed", "CDC sources the sweep has processed so far").set(processed)
    meter.create_gauge("cdc_sweeper_sources_errored", "CDC sources the sweep failed on so far").set(errored)


def record_sweep_completed() -> None:
    _meter().create_gauge("cdc_sweeper_completed_at_seconds", "Unix time the sweep completed", "s").set(
        int(time.time())
    )
