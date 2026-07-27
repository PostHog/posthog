"""
Facade re-exports for task-run stream observability.

The SSE stream view records connection lifecycle metrics (open/close/length/resume-gap)
and labels them by origin product. These are framework-free observability primitives; the
view imports them from here rather than reaching the internal ``metrics`` module.
"""

from products.tasks.backend.metrics import (
    StreamConnectionOutcome,
    observe_stream_connection_closed,
    observe_stream_connection_opened,
    observe_stream_length_on_connect,
    observe_stream_resume_gap,
    origin_product_label,
)

__all__ = [
    "StreamConnectionOutcome",
    "observe_stream_connection_closed",
    "observe_stream_connection_opened",
    "observe_stream_length_on_connect",
    "observe_stream_resume_gap",
    "origin_product_label",
]
