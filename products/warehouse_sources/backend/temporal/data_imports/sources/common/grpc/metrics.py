"""OpenTelemetry instruments for the tracked gRPC transport.

Mirrors `common/http/metrics.py`. The full gRPC method string
(`/package.Service/Method`) is itself low-cardinality, a handful of RPCs per
source, so it is safe to use directly as a metric label. Only the request
counter carries `team_id`: on the histograms it would multiply every team by
every bucket, and the per-team breakdown of latency and size is in the logs.

Source gRPC calls run inside activities, so the instruments come from the
activity meter. Outside an activity (unit tests, a shell) they record nothing.
Instruments are created per call and never cached, because the activity meter
carries the labels of the activity that is running.
"""

from __future__ import annotations

import grpc
from temporalio import activity
from temporalio.common import MetricCounter, MetricHistogram, MetricMeter


def _meter() -> MetricMeter:
    return activity.metric_meter() if activity.in_activity() else MetricMeter.noop


def get_grpc_requests_counter(team_id: int, source_type: str) -> MetricCounter:
    return (
        _meter()
        .with_additional_attributes({"team_id": str(team_id), "source_type": source_type})
        .create_counter(
            "data_import_grpc_requests_total",
            "Outbound gRPC calls issued by warehouse source syncs.",
        )
    )


def get_grpc_response_bytes_histogram(source_type: str) -> MetricHistogram:
    return (
        _meter()
        .with_additional_attributes({"source_type": source_type})
        .create_histogram(
            "data_import_grpc_response_bytes",
            "Serialized size of gRPC response messages in bytes.",
            unit="By",
        )
    )


def get_grpc_latency_histogram(source_type: str) -> MetricHistogram:
    return (
        _meter()
        .with_additional_attributes({"source_type": source_type})
        .create_histogram(
            "data_import_grpc_latency_ms",
            "Outbound gRPC call latency in milliseconds (time to completion).",
            unit="ms",
        )
    )


# gRPC status codes grouped into low-cardinality buckets. RESOURCE_EXHAUSTED
# (quota) gets its own bucket because it's the dominant failure mode for
# warehouse syncs and operators want to alert on it specifically.
_CLIENT_ERROR_CODES = frozenset(
    {
        grpc.StatusCode.INVALID_ARGUMENT,
        grpc.StatusCode.NOT_FOUND,
        grpc.StatusCode.ALREADY_EXISTS,
        grpc.StatusCode.PERMISSION_DENIED,
        grpc.StatusCode.UNAUTHENTICATED,
        grpc.StatusCode.FAILED_PRECONDITION,
        grpc.StatusCode.OUT_OF_RANGE,
    }
)
_UNAVAILABLE_CODES = frozenset(
    {
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.ABORTED,
    }
)


def status_class(code: grpc.StatusCode | None) -> str:
    """Map a `grpc.StatusCode` to a low-cardinality bucket string."""
    if code is None:
        return "error"
    if code == grpc.StatusCode.OK:
        return "ok"
    if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
        return "resource_exhausted"
    if code in _CLIENT_ERROR_CODES:
        return "client_error"
    if code in _UNAVAILABLE_CODES:
        return "unavailable"
    # INTERNAL, UNKNOWN, DATA_LOSS, UNIMPLEMENTED, CANCELLED, and anything else.
    return "server_error"
