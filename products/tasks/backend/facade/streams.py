"""
Facade re-exports for the task-run event stream.

The Redis stream primitives and the ASGI ingest handler are behavioral wiring: core's ASGI
app mounts the ingest handler, and Max's sandbox mode reads a run's live stream through the
stream client. The SSE stream view also reads the connection-wait tuning constants and the
dedicated-stream flag helper from here.
"""

from products.tasks.backend.logic.stream.event_ingest import handle_task_run_event_ingest
from products.tasks.backend.logic.stream.redis_stream import (
    TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
    TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS,
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
)
from products.tasks.backend.redis import run_uses_dedicated_stream

__all__ = [
    "TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS",
    "TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS",
    "TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS",
    "TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS",
    "TaskRunRedisStream",
    "TaskRunStreamError",
    "get_task_run_stream_key",
    "handle_task_run_event_ingest",
    "run_uses_dedicated_stream",
]
