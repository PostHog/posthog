from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from opentelemetry import (
    context as otel_context,
    trace,
)
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

_SPAN_ID_BITS = 64


def run_span_context(run_id: str) -> SpanContext | None:
    # otel-trace-builder.ts and run_log_mirror.py derive the same trace id. Change all three together.
    try:
        run_uuid = UUID(run_id)
    except ValueError:
        return None
    return SpanContext(
        trace_id=run_uuid.int,
        span_id=run_uuid.int & ((1 << _SPAN_ID_BITS) - 1),
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )


@contextmanager
def run_trace_context(run_id: str, *, enabled: bool) -> Iterator[None]:
    span_context = run_span_context(run_id) if enabled else None
    if span_context is None:
        yield
        return

    token = otel_context.attach(trace.set_span_in_context(NonRecordingSpan(span_context)))
    try:
        yield
    finally:
        otel_context.detach(token)
