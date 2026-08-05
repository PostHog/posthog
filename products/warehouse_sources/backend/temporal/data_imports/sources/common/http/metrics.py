"""OpenTelemetry instruments for the tracked HTTP transport.

Cardinality is bounded by `(team_id, source_type, host, status_class)`.
Schema id, job id, and the full URL deliberately do not appear as metric
labels — they live in logs only.

`workflow.metric_meter()` is only valid inside a Temporal workflow or
activity. Outside of that — for example a unit test that directly drives
the transport without spinning up Temporal — the helpers fall back to
no-op recorders so that tests don't have to mock the workflow runtime.

Instruments are cached per `(team_id, source_type)` so the OTel SDK only
sees one create-call per labelled meter, not one per outbound request.
The cache is per-process, populated lazily, and never invalidated — the
cardinality is bounded by `(team_id × source_type)` which is small in
practice. Tests can call `_reset_cache_for_tests()` to clear it.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Protocol

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


def get_http_requests_counter(team_id: int, source_type: str) -> _CounterLike | MetricCounter:
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
                "data_import_http_requests_total",
                "Outbound HTTP requests issued by warehouse source syncs.",
            )
        _REQUESTS_COUNTER_CACHE[key] = instrument
        return instrument


def get_http_response_bytes_histogram(team_id: int, source_type: str) -> _HistogramLike | MetricHistogram:
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
                "data_import_http_response_bytes",
                "Size of outbound HTTP response bodies in bytes.",
                unit="By",
            )
        _RESPONSE_BYTES_HISTOGRAM_CACHE[key] = instrument
        return instrument


def get_http_latency_histogram(team_id: int, source_type: str) -> _HistogramLike | MetricHistogram:
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
                "data_import_http_latency_ms",
                "Outbound HTTP round-trip latency in milliseconds.",
                unit="ms",
            )
        _LATENCY_HISTOGRAM_CACHE[key] = instrument
        return instrument


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
