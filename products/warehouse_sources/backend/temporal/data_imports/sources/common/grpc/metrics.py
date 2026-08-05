"""OpenTelemetry instruments for the tracked gRPC transport.

Mirrors `common/http/metrics.py`. Cardinality is bounded by
`(team_id, source_type, method, status_class)`. The full gRPC method string
(`/package.Service/Method`) is itself low-cardinality — a handful of RPCs per
source — so it is safe to use directly as a metric label.

`workflow.metric_meter()` is only valid inside a Temporal workflow or
activity. Outside of that — for example a unit test that directly drives the
interceptor without spinning up Temporal — the helpers fall back to no-op
recorders so that tests don't have to mock the workflow runtime.

Instruments are cached per `(team_id, source_type)` so the OTel SDK only sees
one create-call per labelled meter, not one per RPC. The cache is per-process,
populated lazily, and never invalidated. Tests can call
`_reset_cache_for_tests()` to clear it.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Protocol

import grpc
from temporalio import workflow

if TYPE_CHECKING:
    from temporalio.common import MetricCounter, MetricHistogram

logger = logging.getLogger(__name__)


class _NullCounter:
    def add(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None:
        return None


class _NullHistogram:
    def record(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None:
        return None


class _CounterLike(Protocol):
    def add(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None: ...


class _HistogramLike(Protocol):
    def record(self, value: int, additional_attributes: dict[str, Any] | None = None) -> None: ...


_INSTRUMENT_LOCK = threading.Lock()
_REQUESTS_COUNTER_CACHE: dict[tuple[int, str], _CounterLike] = {}
_RESPONSE_BYTES_HISTOGRAM_CACHE: dict[tuple[int, str], _HistogramLike] = {}
_LATENCY_HISTOGRAM_CACHE: dict[tuple[int, str], _HistogramLike] = {}


def _safe_metric_meter() -> Any | None:
    try:
        return workflow.metric_meter()
    except Exception:
        # Not inside a workflow / activity — fall through to no-op recorders.
        return None


def _reset_cache_for_tests() -> None:
    """Test hook — clear the per-`(team_id, source_type)` instrument caches."""
    with _INSTRUMENT_LOCK:
        _REQUESTS_COUNTER_CACHE.clear()
        _RESPONSE_BYTES_HISTOGRAM_CACHE.clear()
        _LATENCY_HISTOGRAM_CACHE.clear()


def get_grpc_requests_counter(team_id: int, source_type: str) -> _CounterLike | MetricCounter:
    key = (team_id, source_type)
    cached = _REQUESTS_COUNTER_CACHE.get(key)
    if cached is not None:
        return cached
    with _INSTRUMENT_LOCK:
        cached = _REQUESTS_COUNTER_CACHE.get(key)
        if cached is not None:
            return cached
        meter = _safe_metric_meter()
        if meter is None:
            instrument: _CounterLike = _NullCounter()
        else:
            instrument = meter.with_additional_attributes(
                {"team_id": str(team_id), "source_type": source_type}
            ).create_counter(
                "data_import_grpc_requests_total",
                "Outbound gRPC calls issued by warehouse source syncs.",
            )
        _REQUESTS_COUNTER_CACHE[key] = instrument
        return instrument


def get_grpc_response_bytes_histogram(team_id: int, source_type: str) -> _HistogramLike | MetricHistogram:
    key = (team_id, source_type)
    cached = _RESPONSE_BYTES_HISTOGRAM_CACHE.get(key)
    if cached is not None:
        return cached
    with _INSTRUMENT_LOCK:
        cached = _RESPONSE_BYTES_HISTOGRAM_CACHE.get(key)
        if cached is not None:
            return cached
        meter = _safe_metric_meter()
        if meter is None:
            instrument: _HistogramLike = _NullHistogram()
        else:
            instrument = meter.with_additional_attributes(
                {"team_id": str(team_id), "source_type": source_type}
            ).create_histogram(
                "data_import_grpc_response_bytes",
                "Serialized size of gRPC response messages in bytes.",
                unit="By",
            )
        _RESPONSE_BYTES_HISTOGRAM_CACHE[key] = instrument
        return instrument


def get_grpc_latency_histogram(team_id: int, source_type: str) -> _HistogramLike | MetricHistogram:
    key = (team_id, source_type)
    cached = _LATENCY_HISTOGRAM_CACHE.get(key)
    if cached is not None:
        return cached
    with _INSTRUMENT_LOCK:
        cached = _LATENCY_HISTOGRAM_CACHE.get(key)
        if cached is not None:
            return cached
        meter = _safe_metric_meter()
        if meter is None:
            instrument: _HistogramLike = _NullHistogram()
        else:
            instrument = meter.with_additional_attributes(
                {"team_id": str(team_id), "source_type": source_type}
            ).create_histogram(
                "data_import_grpc_latency_ms",
                "Outbound gRPC call latency in milliseconds (time to completion).",
                unit="ms",
            )
        _LATENCY_HISTOGRAM_CACHE[key] = instrument
        return instrument


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
