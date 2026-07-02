"""Per-call observer for the tracked gRPC transport.

The interceptors call `record_unary` / `record_stream` once per outbound gRPC
call — both successful and failed. The observer:

- emits a structlog log line with the method, host, status, latency and sizes,
  plus all `JobContext` labels;
- updates OTel counters/histograms labelled by `team_id`, `source_type`,
  `method`, and `status_class`;
- delegates to the sampling subsystem, which is a cheap no-op when capture is
  disabled in Redis.

Both the metrics call and the sampling call are wrapped in `try/except` — the
observer must never raise into the call path. A broken telemetry layer cannot
become a sync failure.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Any

import grpc
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.metrics import (
    get_grpc_latency_histogram,
    get_grpc_requests_counter,
    get_grpc_response_bytes_histogram,
    status_class,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.proto_utils import message_byte_size
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling import maybe_capture
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import (
    JobContext,
    current_job_context,
)

logger = structlog.get_logger(__name__)
_fallback_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GrpcRequestRecord:
    method: str
    host: str
    request_bytes: int
    response_bytes: int
    status_class: str
    status_code_num: int | None
    latency_ms: int
    message_count: int | None
    error_class: str | None


def _elapsed_ms(started_at_monotonic: float) -> int:
    return max(0, int((time.monotonic() - started_at_monotonic) * 1000))


def _status_code_num(code: grpc.StatusCode | None) -> int | None:
    if code is None:
        return None
    try:
        return int(code.value[0])
    except Exception:
        return None


def record_unary(
    *,
    method: str,
    host: str,
    request: Any,
    response: Any,
    code: grpc.StatusCode | None,
    exception: BaseException | None,
    started_at_monotonic: float,
) -> None:
    """Log + meter a single unary-unary gRPC call. Never raises."""
    response_bytes = message_byte_size(response) if response is not None else 0
    record = GrpcRequestRecord(
        method=method,
        host=host,
        request_bytes=message_byte_size(request),
        response_bytes=response_bytes,
        status_class=status_class(code),
        status_code_num=_status_code_num(code),
        latency_ms=_elapsed_ms(started_at_monotonic),
        message_count=1 if response is not None else 0,
        error_class=type(exception).__name__ if exception is not None else None,
    )
    response_messages = [response] if response is not None else []
    _emit(record, request=request, response_messages=response_messages, exception=exception)


def record_stream(
    *,
    method: str,
    host: str,
    request: Any,
    retained_responses: list[Any],
    response_bytes: int,
    message_count: int,
    code: grpc.StatusCode | None,
    exception: BaseException | None,
    started_at_monotonic: float,
) -> None:
    """Log + meter a single unary-stream gRPC call. Never raises."""
    record = GrpcRequestRecord(
        method=method,
        host=host,
        request_bytes=message_byte_size(request),
        response_bytes=response_bytes,
        status_class=status_class(code),
        status_code_num=_status_code_num(code),
        latency_ms=_elapsed_ms(started_at_monotonic),
        message_count=message_count,
        error_class=type(exception).__name__ if exception is not None else None,
    )
    _emit(record, request=request, response_messages=retained_responses, exception=exception)


def _emit(
    record: GrpcRequestRecord,
    *,
    request: Any,
    response_messages: list[Any],
    exception: BaseException | None,
) -> None:
    ctx = current_job_context()
    _emit_log(record, ctx=ctx)
    _emit_metrics(record, ctx=ctx)
    _maybe_capture_sample(record, request=request, response_messages=response_messages, ctx=ctx, exception=exception)


def _emit_log(record: GrpcRequestRecord, *, ctx: JobContext | None) -> None:
    fields: dict[str, Any] = {
        "method": record.method,
        "host": record.host,
        "status_class": record.status_class,
        "status_code": record.status_code_num,
        "latency_ms": record.latency_ms,
        "request_bytes": record.request_bytes,
        "response_bytes": record.response_bytes,
        "message_count": record.message_count,
        "error_class": record.error_class,
    }
    if ctx is not None:
        fields.update(ctx.as_log_fields())

    if record.error_class is not None or record.status_class != "ok":
        logger.warning(f"data_imports.grpc.call {record.method}", **fields)
    else:
        logger.debug(f"data_imports.grpc.call {record.method}", **fields)


def _emit_metrics(record: GrpcRequestRecord, *, ctx: JobContext | None) -> None:
    if ctx is None:
        return
    try:
        attrs = {"method": record.method, "status_class": record.status_class}
        get_grpc_requests_counter(ctx.team_id, ctx.source_type).add(1, attrs)
        get_grpc_latency_histogram(ctx.team_id, ctx.source_type).record(record.latency_ms, attrs)
        if record.response_bytes:
            get_grpc_response_bytes_histogram(ctx.team_id, ctx.source_type).record(record.response_bytes, attrs)
    except Exception:
        _fallback_logger.debug("Failed to record gRPC metric", exc_info=True)


def _maybe_capture_sample(
    record: GrpcRequestRecord,
    *,
    request: Any,
    response_messages: list[Any],
    ctx: JobContext | None,
    exception: BaseException | None,
) -> None:
    if ctx is None:
        return
    try:
        maybe_capture(request=request, response_messages=response_messages, record=record, ctx=ctx)
    except Exception:
        _fallback_logger.debug("Failed to capture gRPC sample", exc_info=True)
