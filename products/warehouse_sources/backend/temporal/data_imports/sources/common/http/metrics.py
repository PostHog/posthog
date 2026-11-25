"""OpenTelemetry instruments for the tracked HTTP transport.

Schema id, job id, and the full URL deliberately do not appear as metric
labels. They live in logs only. Only the request counter carries `team_id`
and `host`. Many sources have a host per customer, so on the histograms either
label would multiply every customer by every bucket. The per-team and per-host
breakdown of latency and size is in the logs.

Source HTTP calls run inside activities, so the instruments come from the
activity meter. Outside an activity (unit tests, a shell) they record nothing.
Instruments are created per call and never cached, because the activity meter
carries the labels of the activity that is running.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.common import MetricCounter, MetricHistogram, MetricMeter


def _meter() -> MetricMeter:
    return activity.metric_meter() if activity.in_activity() else MetricMeter.noop


def get_http_requests_counter(team_id: int, source_type: str) -> MetricCounter:
    return (
        _meter()
        .with_additional_attributes({"team_id": str(team_id), "source_type": source_type})
        .create_counter(
            "data_import_http_requests_total",
            "Outbound HTTP requests issued by warehouse source syncs.",
        )
    )


def get_http_response_bytes_histogram(source_type: str) -> MetricHistogram:
    return (
        _meter()
        .with_additional_attributes({"source_type": source_type})
        .create_histogram(
            "data_import_http_response_bytes",
            "Size of outbound HTTP response bodies in bytes.",
            unit="By",
        )
    )


def get_http_latency_histogram(source_type: str) -> MetricHistogram:
    return (
        _meter()
        .with_additional_attributes({"source_type": source_type})
        .create_histogram(
            "data_import_http_latency_ms",
            "Outbound HTTP round-trip latency in milliseconds.",
            unit="ms",
        )
    )


def status_class(status_code: int | None) -> str:
    if status_code is None:
        return "error"
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "other"
