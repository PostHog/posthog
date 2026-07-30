"""CDC Temporal metrics.

Factory functions over the temporalio activity metric meter, mirroring
`pipeline_v3/metrics.py`. Both the extraction and the orphan-slot sweeper run as
activities, so `activity.metric_meter()` is the right meter for either.

Attribute cardinality is kept to team_id/source_id (sweeper-wide metrics carry no
per-source attributes) to match the pipeline_v3 convention.

CDC activity bodies are also unit-tested by direct instantiation, outside any
activity context, where `activity.metric_meter()` raises. `_meter()` falls back to
the no-op meter there so instrumented code stays safe to call from anywhere.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.common import MetricCounter, MetricGauge, MetricHistogramFloat, MetricMeter


def _meter() -> MetricMeter:
    return activity.metric_meter() if activity.in_activity() else MetricMeter.noop


def _source_meter(team_id: int, source_id: str) -> MetricMeter:
    return _meter().with_additional_attributes({"team_id": str(team_id), "source_id": source_id})


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


def get_extraction_duration_metric(team_id: int, source_id: str, status: str) -> MetricHistogramFloat:
    return (
        _meter()
        .with_additional_attributes({"team_id": str(team_id), "source_id": source_id, "status": status})
        .create_histogram_float("cdc_extraction_duration_seconds", "Duration of CDC extraction runs", "s")
    )


def get_tick_skipped_metric(team_id: int, source_id: str, stuck: bool) -> MetricCounter:
    return (
        _meter()
        .with_additional_attributes({"team_id": str(team_id), "source_id": source_id, "stuck": str(stuck).lower()})
        .create_counter(
            "cdc_ticks_skipped_pending_load_total",
            "Total extraction ticks skipped because a previous run's batches are still loading",
        )
    )


def get_slot_advance_metric(team_id: int, source_id: str) -> MetricCounter:
    return _source_meter(team_id, source_id).create_counter("cdc_slot_advance_total", "Total replication slot advances")


def get_slot_advance_failures_metric(team_id: int, source_id: str) -> MetricCounter:
    return _source_meter(team_id, source_id).create_counter(
        "cdc_slot_advance_failures_total", "Total replication slot advance failures"
    )


def get_deferred_runs_depth_metric(team_id: int, source_id: str) -> MetricGauge:
    return _source_meter(team_id, source_id).create_gauge(
        "cdc_deferred_runs_depth", "Deferred CDC runs awaiting the snapshot→streaming flush"
    )


# ---------------------------------------------------------------------------
# Orphan-slot sweeper
# ---------------------------------------------------------------------------


def get_wal_lag_metric(team_id: int, source_id: str) -> MetricGauge:
    return _source_meter(team_id, source_id).create_gauge("cdc_wal_lag_bytes", "Replication slot WAL lag", "By")


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
