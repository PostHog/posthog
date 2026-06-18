"""
Facade re-exports for the task-run event stream.

The Redis stream primitives and the ASGI ingest handler are behavioral wiring: core's ASGI
app mounts the ingest handler, and Max's sandbox mode reads a run's live stream through the
stream client.
"""

from products.tasks.backend.logic.stream.event_ingest import handle_task_run_event_ingest
from products.tasks.backend.logic.stream.redis_stream import (
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
)

__all__ = [
    "TaskRunRedisStream",
    "TaskRunStreamError",
    "get_task_run_stream_key",
    "handle_task_run_event_ingest",
]
