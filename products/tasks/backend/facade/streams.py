"""
Facade re-exports for the task-run event stream.

The Redis stream primitives and the ASGI ingest handler are behavioral wiring: core's ASGI
app mounts the ingest handler, and Max's sandbox mode reads a run's live stream through the
stream client. The SSE stream view also reads the connection-wait tuning constants and the
dedicated-stream flag helper from here.

``prepare_task_run_sse_stream`` and ``task_run_sse_stream`` are the SSE stream itself, for a
view of any product that serves a run's events: the first resolves the run on the request
thread, the second is the response body.
"""

from products.tasks.backend.feature_flags import run_stream_presence_gated, run_stream_thin_tail
from products.tasks.backend.logic.services.run_log_mirror import MAX_IDENTIFIER_CHARS
from products.tasks.backend.logic.stream.backlog import (
    TaskRunStreamBacklogIndex,
    format_log_cursor,
    parse_log_cursor,
    session_update_type,
)
from products.tasks.backend.logic.stream.event_ingest import (
    handle_task_run_event_ingest,
    handle_task_run_event_ingest_wsgi,
)
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
from products.tasks.backend.logic.stream.sse import (
    TASK_RUN_STREAM_CONNECTION_MAX_SECONDS,
    TaskRunSseStream,
    format_sse_event,
    prepare_task_run_sse_stream,
    sse_body_for_server_gateway,
    task_run_sse_stream,
)
from products.tasks.backend.redis import run_uses_dedicated_stream

__all__ = [
    "MAX_IDENTIFIER_CHARS",
    "TASK_RUN_STREAM_CONNECTION_MAX_SECONDS",
    "TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS",
    "TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS",
    "TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS",
    "TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS",
    "TASK_RUN_STREAM_WATCHED_REFRESH_INTERVAL_SECONDS",
    "TaskRunRedisStream",
    "TaskRunSseStream",
    "TaskRunStreamBacklogIndex",
    "TaskRunStreamError",
    "format_log_cursor",
    "format_sse_event",
    "get_task_run_stream_key",
    "handle_task_run_event_ingest",
    "handle_task_run_event_ingest_wsgi",
    "parse_log_cursor",
    "prepare_task_run_sse_stream",
    "reset_task_run_stream",
    "run_stream_presence_gated",
    "run_stream_thin_tail",
    "run_uses_dedicated_stream",
    "session_update_type",
    "sse_body_for_server_gateway",
    "task_run_sse_stream",
]
