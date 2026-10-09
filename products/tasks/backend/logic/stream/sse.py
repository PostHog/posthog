"""The Server-Sent Events stream of a task run.

Serves the run's live Redis stream, and for thin-tail runs the durable run log before it, as
SSE frames. ``prepare_task_run_sse_stream`` does the database reads on the request thread.
``task_run_sse_stream`` is the long-lived body: it reads Redis and object storage only.
"""

import json
import asyncio
from collections.abc import AsyncGenerator, Callable, Generator
from uuid import UUID

from django.conf import settings

import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.facade import api as tasks_api
from products.tasks.backend.feature_flags import run_stream_presence_gated, run_stream_thin_tail
from products.tasks.backend.logic.services.run_log_mirror import MAX_IDENTIFIER_CHARS
from products.tasks.backend.logic.stream.backlog import (
    TaskRunStreamBacklogIndex,
    format_log_cursor,
    parse_log_cursor,
    session_update_type,
)
from products.tasks.backend.logic.stream.redis_stream import (
    TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
    TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
    TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS,
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
)
from products.tasks.backend.metrics import (
    StreamConnectionOutcome,
    observe_stream_backlog_bytes,
    observe_stream_backlog_gap,
    observe_stream_backlog_oversized,
    observe_stream_backlog_served,
    observe_stream_backlog_throttled,
    observe_stream_connection_closed,
    observe_stream_connection_opened,
    observe_stream_length_on_connect,
    observe_stream_resume_gap,
)
from products.tasks.backend.redis import run_uses_dedicated_stream

from ee.hogai.utils.aio import async_to_sync

logger = structlog.get_logger(__name__)

TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS = 20.0
TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME = "keepalive"
TASK_RUN_STREAM_KEEPALIVE_PAYLOAD = {"type": "keepalive"}
# Long-lived SSE connections pin worker processes during recycle-drain, so
# cap each one: emit `event: end` so clients can tell rotation from run
# completion, then close. Clients resume from their Last-Event-ID cursor.
TASK_RUN_STREAM_CONNECTION_MAX_SECONDS = 15 * 60
TASK_RUN_STREAM_END_EVENT_NAME = "end"
TASK_RUN_STREAM_ROTATED_PAYLOAD = {"type": "rotated"}
# Distinct from the rotation `end` event above: this fires once when the run itself
# completes, so clients stop reconnecting instead of resuming from Last-Event-ID.
TASK_RUN_STREAM_COMPLETE_EVENT_NAME = "stream-end"
# A backlog replay holds its whole parsed run log in memory for the length of the
# replay, and SSE admission is shared across endpoints with no per-user bound, so
# concurrent replays are budgeted by byte size per process. All mutation happens
# on the event loop with no await between check and update, so a plain int is safe.
_backlog_inflight_bytes = 0


def _try_reserve_backlog_bytes(size_bytes: int) -> bool:
    global _backlog_inflight_bytes
    if _backlog_inflight_bytes + size_bytes > settings.TASK_RUN_STREAM_BACKLOG_INFLIGHT_MAX_BYTES:
        return False
    _backlog_inflight_bytes += size_bytes
    return True


def _release_backlog_bytes(size_bytes: int) -> None:
    global _backlog_inflight_bytes
    _backlog_inflight_bytes -= size_bytes


def _parse_backlog(log_content: str) -> tuple[list[dict], TaskRunStreamBacklogIndex]:
    # Runs via asyncio.to_thread: parsing a log at the byte cap takes long
    # enough to stall every other stream on the ASGI event loop.
    entries = list(tasks_api.parse_task_run_log_entries(log_content))
    return entries, TaskRunStreamBacklogIndex(entries)


def _log_field(value: object) -> str | None:
    return None if value is None else str(value)[:MAX_IDENTIFIER_CHARS]


def format_sse_event(data: dict, *, event_id: str | None = None, event_name: str | None = None) -> bytes:
    parts: list[str] = []
    if event_name:
        parts.append(f"event: {event_name}")
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append(f"data: {json.dumps(data)}")
    return ("\n".join(parts) + "\n\n").encode()


@frozen
class TaskRunSseStream:
    """One client connection to a run's event stream: the run facts and where to start."""

    run_id: UUID
    state: dict
    origin_product: str
    is_terminal: bool
    state_event: dict
    last_event_id: str | None
    start_latest: bool
    thin_tail: bool
    # Position in the run log to replay after. None serves no backlog; -1 serves all of it.
    backlog_serve_after: int | None
    backlog_log_urls: list[str]


def prepare_task_run_sse_stream(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    last_event_id: str | None,
    start_latest: bool,
) -> TaskRunSseStream | None:
    """Resolve a run for streaming. ``None`` if the run isn't found. Caller owns task visibility."""
    stream_info = tasks_api.get_task_run_stream_info(run_id, task_id, team_id)
    if stream_info is None:
        return None

    # Thin-tail runs keep only a short live tail in Redis; history is served
    # from the durable run log at connect time, under `log-<n>` event ids.
    # Only cheap resolution happens here — the log read and parse run inside
    # the generator, after SSE admission, off the event loop.
    thin_tail = run_stream_thin_tail(stream_info.state) and not start_latest
    backlog_serve_after: int | None = None
    backlog_log_urls: list[str] = []
    if thin_tail:
        if not last_event_id:
            backlog_serve_after = -1
        else:
            backlog_serve_after = parse_log_cursor(last_event_id)
        backlog_log_urls = tasks_api.get_task_run_log_urls(run_id, task_id, team_id) or []
    return TaskRunSseStream(
        run_id=stream_info.id,
        state=stream_info.state,
        origin_product=stream_info.origin_product,
        is_terminal=stream_info.is_terminal,
        state_event=stream_info.state_event,
        last_event_id=last_event_id,
        start_latest=start_latest,
        thin_tail=thin_tail,
        backlog_serve_after=backlog_serve_after,
        backlog_log_urls=backlog_log_urls,
    )


def sse_body_for_server_gateway(
    make_body: Callable[[], AsyncGenerator[bytes]],
) -> AsyncGenerator[bytes] | Generator[bytes]:
    """The body of an SSE response in the form that the running server gateway can iterate."""
    if settings.SERVER_GATEWAY_INTERFACE == "ASGI":
        return make_body()
    # A WSGI worker cannot iterate an async body, so a thread runs the body and passes on its frames.
    return async_to_sync(make_body)


async def task_run_sse_stream(stream: TaskRunSseStream) -> AsyncGenerator[bytes]:
    stream_key = get_task_run_stream_key(str(stream.run_id))
    use_dedicated_stream = run_uses_dedicated_stream(stream.state)
    presence_gated = run_stream_presence_gated(stream.state)
    redis_stream = TaskRunRedisStream(stream_key, use_dedicated_stream)
    connection_started_at = asyncio.get_running_loop().time()
    # Default to client_disconnect: any exit that isn't an explicit
    # completion/error/unavailable is the client (or proxy) going away.
    outcome: StreamConnectionOutcome = "client_disconnect"
    # Record opened inside the try so the closed counter only fires when
    # the open succeeded — keeps opened/closed balanced for the
    # active-connections gauge regardless of which increment fails.
    opened = False
    resume_cursor = stream.last_event_id
    serve_after = stream.backlog_serve_after
    backlog_index: TaskRunStreamBacklogIndex | None = None
    backlog_contiguity_pending = False

    try:
        observe_stream_connection_opened(stream.origin_product)
        opened = True
        delay = TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS
        wait_started_at = asyncio.get_running_loop().time()
        last_keepalive_at = wait_started_at
        await redis_stream.refresh_watched()

        if stream.thin_tail and serve_after is None and resume_cursor:
            # A Redis-id reconnect whose resume point was trimmed — or
            # whose stream key expired entirely — would silently skip
            # the evicted interval; fall back to a full backlog replay
            # instead (at-least-once, per the endpoint description).
            # Best-effort: never break the stream.
            try:
                stream_exists = await redis_stream.exists()
                if not stream_exists or await redis_stream.resume_point_trimmed(resume_cursor):
                    observe_stream_resume_gap(stream.origin_product)
                    logger.warning(
                        "task_run_stream_resume_gap",
                        stream_key=stream_key,
                        last_event_id=_log_field(resume_cursor),
                        reason="trimmed" if stream_exists else "expired",
                    )
                    serve_after = -1
            except Exception:
                logger.warning("task_run_stream_attach_observe_failed", stream_key=stream_key, exc_info=True)

        if serve_after is not None:
            resume_cursor = None
            backlog_reserved = 0
            try:
                try:
                    backlog_bytes = await asyncio.to_thread(tasks_api.get_task_run_log_size, stream.backlog_log_urls)
                    observe_stream_backlog_bytes(stream.origin_product, backlog_bytes)
                    backlog_oversized = backlog_bytes > settings.TASK_RUN_STREAM_BACKLOG_MAX_BYTES
                    if backlog_oversized:
                        # Parsing a log past the byte cap risks the worker's
                        # memory; degrade to the plain Redis window instead.
                        observe_stream_backlog_oversized(stream.origin_product)
                        logger.warning(
                            "task_run_stream_backlog_oversized",
                            stream_key=stream_key,
                            backlog_bytes=backlog_bytes,
                        )
                        log_content = ""
                    elif not _try_reserve_backlog_bytes(backlog_bytes):
                        # The worker already holds its budget's worth of parsed
                        # logs; refuse this replay so RSS stays bounded no matter
                        # how many connections arrive. Transient — retryable.
                        outcome = "backlog_busy"
                        observe_stream_backlog_throttled(stream.origin_product)
                        logger.warning(
                            "task_run_stream_backlog_throttled",
                            stream_key=stream_key,
                            backlog_bytes=backlog_bytes,
                        )
                        yield format_sse_event({"error": "Backlog busy"}, event_name="error")
                        return
                    else:
                        backlog_reserved = backlog_bytes
                        log_content = await asyncio.to_thread(
                            tasks_api.read_task_run_log_content, stream.backlog_log_urls
                        )
                    backlog_entries, backlog_index = await asyncio.to_thread(_parse_backlog, log_content)
                    del log_content
                except Exception:
                    outcome = "backlog_error"
                    logger.exception("task_run_stream_backlog_read_failed", stream_key=stream_key)
                    yield format_sse_event({"error": "Backlog unavailable"}, event_name="error")
                    return
                # An oversized backlog serves nothing, so an empty index would
                # flag every stamped live entry as a false gap — skip the check.
                backlog_contiguity_pending = not backlog_oversized
                if serve_after >= len(backlog_entries):
                    # Cursor beyond the loaded log: not one we issued — replay in full.
                    serve_after = -1
                backlog_served = 0
                try:
                    for backlog_position in range(serve_after + 1, len(backlog_entries)):
                        yield format_sse_event(
                            backlog_entries[backlog_position],
                            event_id=format_log_cursor(backlog_position),
                        )
                        backlog_served += 1
                        await redis_stream.refresh_watched()
                        now = asyncio.get_running_loop().time()
                        if now - connection_started_at >= TASK_RUN_STREAM_CONNECTION_MAX_SECONDS:
                            outcome = "rotated"
                            yield format_sse_event(
                                TASK_RUN_STREAM_ROTATED_PAYLOAD,
                                event_name=TASK_RUN_STREAM_END_EVENT_NAME,
                            )
                            return
                finally:
                    # In a finally so a client that goes away mid-replay still
                    # counts the frames it was sent.
                    observe_stream_backlog_served(stream.origin_product, backlog_served)
                backlog_entries.clear()
            finally:
                # Covers every exit — replay done, rotation, read failure,
                # client disconnect mid-replay — so the budget never leaks.
                if backlog_reserved:
                    _release_backlog_bytes(backlog_reserved)

        waited_for_stream = False
        while not await redis_stream.exists():
            if stream.is_terminal:
                outcome = "drained"
                yield format_sse_event(stream.state_event)
                yield format_sse_event({"status": "complete"}, event_name=TASK_RUN_STREAM_COMPLETE_EVENT_NAME)
                return
            waited_for_stream = True
            if presence_gated:
                break
            now = asyncio.get_running_loop().time()
            await redis_stream.refresh_watched()
            if now - wait_started_at >= TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS:
                outcome = "unavailable"
                yield format_sse_event({"error": "Stream not available"}, event_name="error")
                return

            if now - last_keepalive_at >= TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS:
                last_keepalive_at = now
                yield format_sse_event(
                    TASK_RUN_STREAM_KEEPALIVE_PAYLOAD,
                    event_name=TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME,
                )

            await asyncio.sleep(delay)
            delay = min(
                delay + TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
                TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
            )

        # Only reconnects (Last-Event-ID set) can suffer a trimmed resume
        # point, and that's the only case where stream depth vs the trim
        # cap is interesting — so skip the extra Redis reads on fresh
        # connects. Best-effort: never break the stream.
        if resume_cursor:
            try:
                observe_stream_length_on_connect(await redis_stream.get_length())
                if await redis_stream.resume_point_trimmed(resume_cursor):
                    observe_stream_resume_gap(stream.origin_product)
                    logger.warning(
                        "task_run_stream_resume_gap",
                        stream_key=stream_key,
                        last_event_id=_log_field(resume_cursor),
                        reason="trimmed",
                    )
            except Exception:
                logger.warning("task_run_stream_attach_observe_failed", stream_key=stream_key, exc_info=True)

        start_id = resume_cursor or "0"
        if not resume_cursor and stream.start_latest and not waited_for_stream:
            start_id = await redis_stream.get_latest_stream_id() or "0"
            backlog_contiguity_pending = False
        try:
            async for stream_item in redis_stream.read_stream_entries(
                start_id=start_id,
                keepalive_interval_seconds=TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS,
            ):
                if stream_item is None:
                    yield format_sse_event(
                        TASK_RUN_STREAM_KEEPALIVE_PAYLOAD,
                        event_name=TASK_RUN_STREAM_KEEPALIVE_EVENT_NAME,
                    )
                else:
                    event_id, event = stream_item
                    if backlog_contiguity_pending and backlog_index is not None and event.get("event_id"):
                        # Oldest id-carrying live entry: a hole before it means
                        # Redis evicted events whose log batch never landed — the
                        # loss mode thin-tail trimming assumes away. Count it
                        # before rollout.
                        backlog_contiguity_pending = False
                        if backlog_index.has_gap_before(event):
                            observe_stream_backlog_gap(stream.origin_product)
                            logger.warning(
                                "task_run_stream_backlog_gap",
                                stream_key=stream_key,
                                event_id=_log_field(event.get("event_id")),
                                session_update=_log_field(session_update_type(event)),
                                reason="log_behind_trim",
                            )
                    if backlog_index is None or not backlog_index.covers(event):
                        yield format_sse_event(event, event_id=event_id)
                now = asyncio.get_running_loop().time()
                await redis_stream.refresh_watched()
                if now - connection_started_at >= TASK_RUN_STREAM_CONNECTION_MAX_SECONDS:
                    outcome = "rotated"
                    # Without this marker a rotation EOF would be
                    # indistinguishable from run completion for API
                    # consumers reading until EOF.
                    yield format_sse_event(
                        TASK_RUN_STREAM_ROTATED_PAYLOAD,
                        event_name=TASK_RUN_STREAM_END_EVENT_NAME,
                    )
                    return
            outcome = "completed"
            # read_stream_entries only returns on the completion sentinel; emit an
            # explicit terminal event so the client stops reconnecting without
            # consulting run status (a dropped connection never reaches here).
            yield format_sse_event({"status": "complete"}, event_name=TASK_RUN_STREAM_COMPLETE_EVENT_NAME)
        except TaskRunStreamError as e:
            outcome = "stream_error"
            logger.error("TaskRunRedisStream error for stream %s: %s", stream_key, e, exc_info=True)
            yield format_sse_event({"error": str(e)}, event_name="error")
    finally:
        if opened:
            duration = asyncio.get_running_loop().time() - connection_started_at
            observe_stream_connection_closed(stream.origin_product, outcome, duration)
