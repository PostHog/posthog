"""
Facade re-exports for the task-run event stream.

The Redis stream primitives and the ASGI ingest handler are behavioral wiring: core's ASGI
app mounts the ingest handler, and Max's sandbox mode reads a run's live stream through the
stream client. The SSE stream view also reads the connection-wait tuning constants and the
dedicated-stream flag helper from here.
"""

from products.tasks.backend.feature_flags import run_stream_presence_gated, run_stream_thin_tail
from products.tasks.backend.logic.stream.backlog import TaskRunStreamBacklogIndex, format_log_cursor, parse_log_cursor
from products.tasks.backend.logic.stream.event_ingest import handle_task_run_event_ingest
from products.tasks.backend.logic.stream.redis_stream import (
    TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
    TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS,
    TASK_RUN_STREAM_WATCHED_REFRESH_INTERVAL_SECONDS,
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
    reset_task_run_stream,
)
from products.tasks.backend.redis import run_uses_dedicated_stream

__all__ = [
    "TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS",
    "TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS",
    "TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS",
    "TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS",
    "TASK_RUN_STREAM_WATCHED_REFRESH_INTERVAL_SECONDS",
    "TaskRunRedisStream",
    "TaskRunStreamBacklogIndex",
    "TaskRunStreamError",
    "format_log_cursor",
    "get_task_run_stream_key",
    "handle_task_run_event_ingest",
    "parse_log_cursor",
    "reset_task_run_stream",
    "run_stream_presence_gated",
    "run_stream_thin_tail",
    "run_uses_dedicated_stream",
]
