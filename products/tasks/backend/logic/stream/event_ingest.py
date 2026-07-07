from __future__ import annotations

import re
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections

import structlog
import posthoganalytics
from asgiref.sync import sync_to_async
from jwt import PyJWTError

from products.tasks.backend.constants import STREAM_VIA_PROXY_FEATURE_FLAG
from products.tasks.backend.logic.services.connection_token import (
    SandboxEventIngestTokenPayload,
    validate_sandbox_event_ingest_token,
)
from products.tasks.backend.logic.stream.redis_stream import (
    TaskRunRedisStream,
    TaskRunStreamAlreadyCompleted,
    TaskRunStreamCompletionSequenceMismatch,
    TaskRunStreamSequenceGap,
    get_task_run_stream_key,
)
from products.tasks.backend.models import TaskRun
from products.tasks.backend.push_dispatcher import notify_task_run_awaiting_input
from products.tasks.backend.redis import run_uses_dedicated_stream

from ee.hogai.sandbox import is_turn_complete

logger = structlog.get_logger(__name__)

TASK_RUN_EVENT_INGEST_ROUTE = re.compile(
    r"^/api/projects/(?P<project_id>[^/]+)/tasks/(?P<task_id>[^/]+)/runs/(?P<run_id>[^/]+)/event_stream/?$"
)
HEARTBEAT_THROTTLE_SECONDS = 30
MAX_EVENT_LINE_BYTES = 1_000_000
MAX_REQUEST_BYTES = 5_000_000
MAX_EVENTS_PER_REQUEST = 1_000
STREAM_COMPLETE_CONTROL_TYPE = "_posthog/stream_complete"

ASGIMessage = dict[str, object]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]


class ClientDisconnected(Exception):
    pass


class EventIngestBadRequest(Exception):
    pass


class EventIngestPayloadTooLarge(Exception):
    def __init__(self, message: str, last_accepted_seq: int = 0):
        super().__init__(message)
        self.last_accepted_seq = last_accepted_seq


class EventIngestHTTPError(Exception):
    def __init__(self, status_code: int, payload: dict):
        super().__init__(payload.get("error", "Event ingest request failed"))
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True)
class EventIngestRoute:
    project_id: str
    task_id: str
    run_id: str


@dataclass
class EventIngestResult:
    accepted: int = 0
    duplicate: int = 0
    last_accepted_seq: int = 0


@dataclass
class EventIngestEventLine:
    sequence: int
    event: dict


@dataclass
class EventIngestCompleteLine:
    final_sequence: int


async def handle_task_run_event_ingest(scope: ASGIMessage, receive: ASGIReceive, send: ASGISend) -> bool:
    """Handle sandbox-to-Django streaming event ingest before Django buffers the request body."""
    if scope.get("type") != "http":
        return False

    path = scope.get("path")
    if not isinstance(path, str):
        return False

    route = _match_event_ingest_route(path)
    if route is None:
        return False

    if scope.get("method") != "POST":
        await _send_json(send, 405, {"error": "Method not allowed"})
        return True

    try:
        claims = await _authorize_event_ingest_request(scope, route)
    except EventIngestHTTPError as error:
        await _send_json(send, error.status_code, error.payload)
        return True

    # Write to the instance the run is pinned to so its SSE reader and relay tail the same stream.
    state = await TaskRun.objects.filter(id=claims.run_id).values_list("state", flat=True).afirst()
    redis_stream = TaskRunRedisStream(get_task_run_stream_key(claims.run_id), run_uses_dedicated_stream(state))

    try:
        result = await _ingest_event_lines(
            redis_stream,
            claims.run_id,
            receive,
        )
    except ClientDisconnected:
        logger.info("task_run_event_ingest_client_disconnected", run_id=claims.run_id)
        return True
    except EventIngestBadRequest as error:
        await _send_json(send, 400, {"error": str(error)})
        return True
    except EventIngestPayloadTooLarge as error:
        await _send_json(send, 413, {"error": str(error), "last_accepted_seq": error.last_accepted_seq})
        return True
    except TaskRunStreamSequenceGap as error:
        await _send_json(send, 409, {"error": str(error), "last_accepted_seq": error.last_accepted_seq})
        return True
    except TaskRunStreamAlreadyCompleted as error:
        await _send_json(send, 409, {"error": str(error), "last_accepted_seq": error.last_accepted_seq})
        return True
    except TaskRunStreamCompletionSequenceMismatch as error:
        await _send_json(send, 409, {"error": str(error), "last_accepted_seq": error.last_accepted_seq})
        return True

    await _send_json(
        send,
        200,
        {
            "accepted": result.accepted,
            "duplicate": result.duplicate,
            "last_accepted_seq": result.last_accepted_seq,
        },
    )
    return True


async def _ingest_event_lines(
    redis_stream: TaskRunRedisStream,
    run_id: str,
    receive: ASGIReceive,
) -> EventIngestResult:
    result = EventIngestResult(last_accepted_seq=await redis_stream.get_last_sequence())

    event_count = 0
    completion_line_final_sequence: int | None = None
    try:
        async for line in _iter_request_lines(receive):
            parsed_line = _parse_ingest_line(line)
            if isinstance(parsed_line, EventIngestCompleteLine):
                if completion_line_final_sequence is not None:
                    raise EventIngestBadRequest("Completion line must be the final event stream line")
                completion_line_final_sequence = parsed_line.final_sequence
                continue

            if completion_line_final_sequence is not None:
                raise EventIngestBadRequest("Completion line must be the final event stream line")

            event_count += 1
            if event_count > MAX_EVENTS_PER_REQUEST:
                raise EventIngestPayloadTooLarge("Too many events in request", result.last_accepted_seq)

            sequence = parsed_line.sequence
            event = parsed_line.event
            stream_id = await redis_stream.write_event_with_sequence(event, sequence)
            if stream_id is None:
                result.duplicate += 1
                result.last_accepted_seq = max(result.last_accepted_seq, await redis_stream.get_last_sequence())
                continue

            result.accepted += 1
            result.last_accepted_seq = sequence
            await _heartbeat_workflow_if_needed(redis_stream, run_id, event)
    except EventIngestPayloadTooLarge as error:
        if result.last_accepted_seq and error.last_accepted_seq == 0:
            error.last_accepted_seq = result.last_accepted_seq
        raise

    if completion_line_final_sequence is not None:
        await redis_stream.mark_complete_after_sequence(completion_line_final_sequence)

    return result


async def _iter_request_lines(receive: ASGIReceive) -> AsyncGenerator[str]:
    """Yield NDJSON request lines with bounded event-loop work per request."""
    buffer = b""
    request_size = 0

    while True:
        message = await receive()
        message_type = message.get("type")
        if message_type == "http.disconnect":
            raise ClientDisconnected
        if message_type != "http.request":
            continue

        body = message.get("body", b"")
        if isinstance(body, bytes) and body:
            request_size += len(body)
            if request_size > MAX_REQUEST_BYTES:
                raise EventIngestPayloadTooLarge("Event ingest request is too large")

            buffer += body
            if len(buffer) > MAX_EVENT_LINE_BYTES and b"\n" not in buffer:
                raise EventIngestPayloadTooLarge("Event line is too large")

            lines = buffer.split(b"\n")
            buffer = lines.pop() or b""
            for line in lines:
                if len(line) > MAX_EVENT_LINE_BYTES:
                    raise EventIngestPayloadTooLarge("Event line is too large")
                stripped = line.strip()
                if stripped:
                    yield _decode_line(stripped)

        if not message.get("more_body", False):
            stripped = buffer.strip()
            if stripped:
                if len(stripped) > MAX_EVENT_LINE_BYTES:
                    raise EventIngestPayloadTooLarge("Event line is too large")
                yield _decode_line(stripped)
            return


def _decode_line(line: bytes) -> str:
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EventIngestBadRequest("Invalid UTF-8 in event stream") from error


def _parse_ingest_line(line: str) -> EventIngestEventLine | EventIngestCompleteLine:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        raise EventIngestBadRequest("Invalid JSON line") from error

    if not isinstance(payload, dict):
        raise EventIngestBadRequest("Each event line must be a JSON object")

    if payload.get("type") == STREAM_COMPLETE_CONTROL_TYPE:
        final_sequence = payload.get("final_seq")
        if type(final_sequence) is not int or final_sequence < 0:
            raise EventIngestBadRequest("Completion final sequence must be a non-negative integer")
        return EventIngestCompleteLine(final_sequence=final_sequence)

    sequence = payload.get("seq")
    event = payload.get("event")
    if type(sequence) is not int or sequence < 1:
        raise EventIngestBadRequest("Event sequence must be a positive integer")
    if not isinstance(event, dict):
        raise EventIngestBadRequest("Event payload must be an object")

    return EventIngestEventLine(sequence=sequence, event=event)


async def _heartbeat_workflow_if_needed(redis_stream: TaskRunRedisStream, run_id: str, event: dict) -> None:
    if is_turn_complete(event):
        await redis_stream.set_agent_active(False)
        await _dispatch_awaiting_input_if_interactive(run_id)
        return

    if _is_session_update(event):
        await redis_stream.set_agent_active(True)
        agent_active = True
    else:
        agent_active = await redis_stream.get_agent_active()

    if not agent_active:
        return

    if not await redis_stream.claim_agent_active_heartbeat(HEARTBEAT_THROTTLE_SECONDS):
        return

    await sync_to_async(_heartbeat_workflow, thread_sensitive=True)(run_id, agent_active)


def _heartbeat_workflow(run_id: str, agent_active: bool) -> None:
    # This runs on a sync_to_async thread that Django never health-checks (the ASGI wrapper
    # intercepts the request before Django's connection lifecycle runs), so a pooled connection
    # Postgres has since closed can be reused. Mirror push_dispatcher/custom_prompt_internals and
    # clear stale connections first. Gated on `not settings.TEST` since it trips pytest-django's
    # DB-access guard when the ORM read is patched.
    if not settings.TEST:
        close_old_connections()

    try:
        task_run = TaskRun.objects.get(id=run_id)
    except TaskRun.DoesNotExist:
        logger.warning("task_run_event_ingest_heartbeat_run_missing", run_id=run_id)
        return

    task_run.heartbeat_workflow(agent_active=agent_active)


async def _dispatch_awaiting_input_if_interactive(run_id: str) -> None:
    """Notify when an interactive run finishes a turn and idles for input."""
    await sync_to_async(_dispatch_awaiting_input_if_interactive_sync, thread_sensitive=True)(run_id)


def _dispatch_awaiting_input_if_interactive_sync(run_id: str) -> None:
    if not settings.TEST:
        close_old_connections()

    try:
        task_run = TaskRun.objects.select_related("task__created_by", "team").get(id=run_id)
    except TaskRun.DoesNotExist:
        logger.warning("task_run_event_ingest_awaiting_input_run_missing", run_id=run_id)
        return

    if task_run.mode != "interactive":
        return

    if not _awaiting_input_push_enabled(task_run):
        return

    notify_task_run_awaiting_input(task_run)


def _awaiting_input_push_enabled(task_run: TaskRun) -> bool:
    """Awaiting-input pushes ship with the proxy-streaming rollout: gate them on the same flag
    so deploying this code changes nothing until the rollout starts. Local dev disables the
    analytics SDK, so the flag never evaluates there; DEBUG is the opt-in, mirroring the
    stream_token endpoint. Fails closed on flag-evaluation errors."""
    if settings.DEBUG:
        return True
    user = task_run.task.created_by
    if user is None:
        return False
    organization_id = str(task_run.team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                STREAM_VIA_PROXY_FEATURE_FLAG,
                user.distinct_id or f"user_{user.id}",
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def _is_session_update(event: dict) -> bool:
    if event.get("type") != "notification":
        return False
    notification = event.get("notification", {})
    return isinstance(notification, dict) and notification.get("method") == "session/update"


def _task_run_exists_sync(run_id: str, task_id: str, team_id: int) -> bool:
    if not settings.TEST:
        close_old_connections()
    return TaskRun.objects.filter(id=run_id, task_id=task_id, team_id=team_id).exists()


async def _task_run_exists(run_id: str, task_id: str, team_id: int) -> bool:
    """Existence check on a sync_to_async thread whose pooled connection Django never
    health-checks. `close_old_connections()` clears a stale connection before the read; a
    single retry recovers a transparent reconnect since this is a side-effect-free read.
    An uncaught OperationalError here would otherwise crash the whole ingest request."""
    run_check = sync_to_async(_task_run_exists_sync, thread_sensitive=True)
    try:
        return await run_check(run_id, task_id, team_id)
    except (OperationalError, InterfaceError):
        logger.warning("task_run_event_ingest_exists_db_reconnect", run_id=run_id, exc_info=True)
        return await run_check(run_id, task_id, team_id)


def _get_bearer_token(scope: ASGIMessage) -> str | None:
    authorization = _get_header(scope, b"authorization")
    if authorization is None:
        return None

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    return token or None


def _match_event_ingest_route(path: str) -> EventIngestRoute | None:
    route_match = TASK_RUN_EVENT_INGEST_ROUTE.match(path)
    if route_match is None:
        return None
    return EventIngestRoute(
        project_id=route_match.group("project_id"),
        task_id=route_match.group("task_id"),
        run_id=route_match.group("run_id"),
    )


async def _authorize_event_ingest_request(
    scope: ASGIMessage, route: EventIngestRoute
) -> SandboxEventIngestTokenPayload:
    token = _get_bearer_token(scope)
    if token is None:
        raise EventIngestHTTPError(401, {"error": "Missing authorization bearer token"})

    try:
        claims = await sync_to_async(validate_sandbox_event_ingest_token, thread_sensitive=False)(token)
    except PyJWTError as error:
        raise EventIngestHTTPError(
            401,
            {"error": "Invalid event ingest token", "code": error.__class__.__name__},
        ) from error

    if claims.task_id != route.task_id or claims.run_id != route.run_id:
        raise EventIngestHTTPError(403, {"error": "Token does not match task run"})
    if route.project_id != "@current" and (not route.project_id.isdigit() or int(route.project_id) != claims.team_id):
        raise EventIngestHTTPError(403, {"error": "Token does not match project"})

    if not await _task_run_exists(claims.run_id, claims.task_id, claims.team_id):
        raise EventIngestHTTPError(404, {"error": "Task run not found"})

    return claims


def _get_header(scope: ASGIMessage, header_name: bytes) -> str | None:
    raw_headers = scope.get("headers", [])
    headers = cast(list[tuple[bytes, bytes]], raw_headers)
    for name, value in headers:
        if name.lower() == header_name:
            return value.decode("utf-8")
    return None


async def _send_json(send: ASGISend, status_code: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
