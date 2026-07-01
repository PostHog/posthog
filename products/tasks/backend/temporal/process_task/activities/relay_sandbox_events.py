from __future__ import annotations

import json
import time
import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import httpx_sse
import structlog
import temporalio.client
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.services.agent_command import validate_sandbox_url
from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.logic.services.permission_broker import (
    parse_permission_request,
    try_auto_respond_permission_request,
)
from products.tasks.backend.logic.stream.redis_stream import TaskRunRedisStream, get_task_run_stream_key
from products.tasks.backend.models import (
    Task as TaskModel,
    TaskRun as TaskRunModel,
)
from products.tasks.backend.redis import run_uses_dedicated_stream
from products.tasks.backend.temporal.constants import INACTIVITY_TIMEOUT_DEFAULT_SECONDS, resolve_inactivity_timeout
from products.tasks.backend.temporal.process_task.utils import (
    get_actor_distinct_id,
    get_task_run_credential_user,
    is_slack_interaction_state,
)

from ee.hogai.sandbox import is_turn_complete

logger = structlog.get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30
SSE_CONNECT_TIMEOUT_SECONDS = 30
SSE_READ_TIMEOUT_SECONDS = 300  # 5 min per chunk
MAX_RECONNECT_ATTEMPTS = 5

TERMINAL_NOTIFICATION_METHODS = frozenset(
    {
        "_posthog/task_complete",
        "_posthog/error",
    }
)


@dataclass
class RelaySandboxEventsInput:
    run_id: str
    task_id: str
    sandbox_url: str
    sandbox_connect_token: str | None
    team_id: int
    distinct_id: str
    sandbox_id: str | None = None
    # When True + slack_thread_context set, the relay forwards per-turn signals
    # to the parent to drive SlackAgentDesignRelayWorkflow children.
    slack_thread_context: dict[str, Any] | None = None
    is_agent_design_enabled: bool = False


@activity.defn
@close_db_connections
async def relay_sandbox_events(input: RelaySandboxEventsInput) -> None:
    """Long-running activity that relays SSE events from a sandbox agent to a Redis stream.

    Connects to the sandbox's GET /events SSE endpoint and writes each event
    into a per-task-run Redis stream for the Django SSE endpoint to consume.
    """
    validation_error = validate_sandbox_url(input.sandbox_url)
    if validation_error:
        raise ValueError(f"Invalid sandbox URL: {validation_error}")

    task_run = await TaskRunModel.objects.select_related("task__created_by", "task__team").aget(id=input.run_id)

    # Match the freshness window to the workflow's inactivity timeout for this run
    # so the heartbeat suppression below never resets a timer it shouldn't.
    origin_product = task_run.task.origin_product
    is_user_origin = not origin_product or origin_product == TaskModel.OriginProduct.USER_CREATED.value
    inactivity_timeout_seconds = resolve_inactivity_timeout(
        is_user_origin=is_user_origin, state=task_run.state
    ).total_seconds()

    stream_key = get_task_run_stream_key(input.run_id)
    redis_stream = TaskRunRedisStream(stream_key, run_uses_dedicated_stream(task_run.state))
    await redis_stream.initialize()

    actor_user = await sync_to_async(get_task_run_credential_user)(task_run.task, task_run.state)
    if is_slack_interaction_state(task_run.state) and actor_user is None:
        raise RuntimeError("Slack task run is missing an acting user")
    connection_token = create_sandbox_connection_token(
        task_run=task_run,
        user_id=actor_user.id if actor_user else 0,
        distinct_id=get_actor_distinct_id(actor_user) if actor_user else input.distinct_id,
    )

    headers = {
        "Authorization": f"Bearer {connection_token}",
        "Accept": "text/event-stream",
    }
    params: dict[str, str] = {}
    if input.sandbox_connect_token:
        params["_modal_connect_token"] = input.sandbox_connect_token

    events_url = f"{input.sandbox_url.rstrip('/')}/events"

    background_logs_enabled = False
    if input.sandbox_id:
        import posthoganalytics

        background_logs_enabled = bool(
            posthoganalytics.feature_enabled(
                "posthog-code-background-agent-logs",
                input.distinct_id,
                send_feature_flag_events=False,
            )
        )

    try:
        await _relay_loop(
            events_url=events_url,
            headers=headers,
            params=params,
            redis_stream=redis_stream,
            run_id=input.run_id,
            task_id=input.task_id,
            sandbox_id=input.sandbox_id,
            background_logs_enabled=background_logs_enabled,
            task_run=task_run,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
            slack_thread_context=input.slack_thread_context,
            is_agent_design_enabled=input.is_agent_design_enabled,
        )
    except asyncio.CancelledError:
        logger.info("relay_sandbox_events_cancelled", run_id=input.run_id)
        # Cancellation is expected when the workflow finishes or is replaced.
        # Do not emit an error sentinel: it makes clients treat a still-valid
        # task run as unrecoverably disconnected.
        await redis_stream.mark_complete()
        raise
    except RuntimeError as e:
        # Interpreter-shutdown race: asyncio uses the default ThreadPoolExecutor
        # for getaddrinfo, and it gets torn down by atexit before in-flight
        # reconnect attempts finish (common under pytest teardown of the eval
        # harness). Exit quietly — logger and Redis are already unusable here,
        # so touching them would cascade into "I/O on closed file" noise.
        if "cannot schedule new futures after shutdown" in str(e):
            return
        logger.exception("relay_sandbox_events_failed", run_id=input.run_id, error=str(e))
        await redis_stream.mark_error(str(e)[:500])
        # The stream now carries an error sentinel — a retried attempt would
        # append events past it that disconnected consumers never see. Fail
        # the activity for good; retries are reserved for attempt-level
        # deaths (worker restart), where no sentinel was written.
        raise ApplicationError(str(e), non_retryable=True) from e
    except Exception as e:
        try:
            marked_complete = await _mark_error_unless_run_is_terminal(redis_stream, input.run_id, str(e))
        except Exception as status_check_error:
            logger.exception(
                "relay_sandbox_events_terminal_status_check_failed",
                run_id=input.run_id,
                relay_error=str(e),
                error=str(status_check_error),
            )
            try:
                await redis_stream.mark_error(str(e)[:500])
            except Exception as mark_error_error:
                logger.exception(
                    "relay_sandbox_events_mark_error_failed",
                    run_id=input.run_id,
                    relay_error=str(e),
                    error=str(mark_error_error),
                )
            logger.exception("relay_sandbox_events_failed", run_id=input.run_id, error=str(e))
        else:
            if marked_complete:
                logger.info("relay_sandbox_events_stopped_after_terminal_run", run_id=input.run_id, error=str(e))
            else:
                logger.exception("relay_sandbox_events_failed", run_id=input.run_id, error=str(e))
        # A complete/error sentinel was written above (or attempted) — same
        # reasoning as the RuntimeError path: don't retry past a sentinel.
        raise ApplicationError(str(e), non_retryable=True) from e


async def _mark_error_unless_run_is_terminal(
    redis_stream: TaskRunRedisStream,
    run_id: str,
    error: str,
) -> bool:
    try:
        task_run = await TaskRunModel.objects.only("status").aget(id=run_id)
    except TaskRunModel.DoesNotExist:
        await redis_stream.mark_error(error[:500])
        return False

    if task_run.status in (
        TaskRunModel.Status.COMPLETED,
        TaskRunModel.Status.FAILED,
        TaskRunModel.Status.CANCELLED,
    ):
        await redis_stream.mark_complete()
        return True

    await redis_stream.mark_error(error[:500])
    return False


async def _background_heartbeat(
    stop_event: asyncio.Event,
    workflow_handle: temporalio.client.WorkflowHandle | None = None,
    last_event_time: list[float] | None = None,
    last_workflow_signal: list[float] | None = None,
    agent_active: list[bool] | None = None,
    inactivity_timeout_seconds: float = INACTIVITY_TIMEOUT_DEFAULT_SECONDS,
) -> None:
    """Heartbeat to Temporal periodically, independent of event flow.

    Also signals the workflow heartbeat when events have been received
    recently and the inline mechanism hasn't signaled recently, preventing
    the inactivity timeout from firing while the agent is actively working.
    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            return  # stop_event was set
        except TimeoutError:
            activity.heartbeat()
            now = time.monotonic()
            if (
                workflow_handle is not None
                and last_event_time is not None
                and last_event_time[0] > 0
                and (now - last_event_time[0]) < inactivity_timeout_seconds
                and (last_workflow_signal is None or (now - last_workflow_signal[0]) >= HEARTBEAT_INTERVAL_SECONDS)
                and (agent_active is None or agent_active[0])
            ):
                if last_workflow_signal is not None:
                    last_workflow_signal[0] = now
                try:
                    await workflow_handle.signal(
                        "heartbeat", arg=agent_active[0] if agent_active is not None else False
                    )
                except Exception as e:
                    logger.warning("relay_workflow_heartbeat_signal_failed", error=str(e))


async def _relay_loop(
    *,
    events_url: str,
    headers: dict[str, str],
    params: dict[str, str],
    redis_stream: TaskRunRedisStream,
    run_id: str,
    task_id: str,
    sandbox_id: str | None = None,
    background_logs_enabled: bool = False,
    task_run: TaskRunModel | None = None,
    inactivity_timeout_seconds: float = INACTIVITY_TIMEOUT_DEFAULT_SECONDS,
    slack_thread_context: dict[str, Any] | None = None,
    is_agent_design_enabled: bool = False,
) -> None:
    """Connect to sandbox SSE and relay events to Redis. Reconnects on transient failures."""
    reconnect_count = 0

    # Get a workflow handle so we can signal the workflow's heartbeat handler,
    # keeping its inactivity timeout from firing while the relay is active.
    workflow_handle: temporalio.client.WorkflowHandle | None = None
    try:
        from posthog.temporal.common.client import async_connect

        temporal_client = await async_connect()
        workflow_id = TaskRunModel.get_workflow_id(task_id, run_id)
        workflow_handle = temporal_client.get_workflow_handle(workflow_id)
    except Exception as e:
        logger.warning("relay_workflow_handle_init_failed", run_id=run_id, error=str(e))

    # Shared mutable state: last time we received an SSE event (monotonic clock).
    # The background heartbeat reads this to decide whether the agent is active.
    last_event_time: list[float] = [0.0]  # list used as mutable container
    last_workflow_signal: list[float] = [0.0]  # shared with background heartbeat
    # Whether the agent is mid-turn. Starts False (idle until a generating
    # session_update) and resets to False on reconnect so a dropped end_of_turn
    # can't leave it stuck True and emit phantom heartbeats.
    agent_active: list[bool] = [False]
    last_audit_ts_ns: list[int] = [0]  # track last agentsh audit timestamp
    # Brackets turn_started / turn_completed signals to the parent.
    slack_turn_active: list[bool] = [False]
    # ACP emits one tool_call + N tool_call_update per id; only render the start.
    emitted_tool_call_ids: set[str] = set()

    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _background_heartbeat(
            stop_heartbeat,
            workflow_handle,
            last_event_time,
            last_workflow_signal,
            agent_active,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
        )
    )

    try:
        while reconnect_count <= MAX_RECONNECT_ATTEMPTS:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=SSE_CONNECT_TIMEOUT_SECONDS,
                        read=SSE_READ_TIMEOUT_SECONDS,
                        write=30.0,
                        pool=30.0,
                    )
                ) as client:
                    async with httpx_sse.aconnect_sse(
                        client,
                        "GET",
                        events_url,
                        headers=headers,
                        params=params,
                    ) as event_source:
                        event_source.response.raise_for_status()
                        last_event_time[0] = time.monotonic()

                        async for sse_event in event_source.aiter_sse():
                            if not sse_event.data:
                                continue

                            try:
                                event_data = json.loads(sse_event.data)
                            except json.JSONDecodeError:
                                logger.warning(
                                    "relay_sandbox_events_invalid_json",
                                    run_id=run_id,
                                    data=sse_event.data[:200],
                                )
                                continue

                            if _is_keepalive_event(event_data):
                                continue

                            await redis_stream.write_event(event_data)
                            if task_run is not None:
                                permission_request = parse_permission_request(event_data)
                                if permission_request is not None:
                                    await asyncio.to_thread(_broker_permission_request, task_run, permission_request)
                            reconnect_count = 0
                            last_event_time[0] = time.monotonic()

                            if _is_end_of_turn(event_data):
                                agent_active[0] = False
                                if sandbox_id and background_logs_enabled:
                                    asyncio.create_task(_emit_agentsh_events(sandbox_id, run_id, last_audit_ts_ns))
                                if task_run is not None and task_run.mode == "interactive":
                                    # Interactive run finished a turn — the agent is now idle waiting
                                    # for the user. Hop off the event loop because the dispatcher
                                    # does sync Redis (cache.add) and a potential network call to
                                    # the feature-flag service.
                                    asyncio.create_task(asyncio.to_thread(_safe_dispatch_awaiting_input, task_run))
                                if is_agent_design_enabled and slack_turn_active[0] and workflow_handle is not None:
                                    slack_turn_active[0] = False
                                    asyncio.create_task(_signal_safely(workflow_handle, "turn_completed"))
                            elif not agent_active[0] and _is_active_agent_update(event_data):
                                agent_active[0] = True

                            # Agent-design signal fan-out: first session/update opens the
                            # child relay; tool_call → step, agent_message_chunk → markdown.
                            if is_agent_design_enabled and workflow_handle is not None:
                                if not slack_turn_active[0] and _is_session_update(event_data):
                                    slack_turn_active[0] = True
                                    asyncio.create_task(
                                        _signal_safely(
                                            workflow_handle,
                                            "turn_started",
                                            arg={"slack_thread_context": slack_thread_context or {}},
                                        )
                                    )
                                if slack_turn_active[0]:
                                    step_payload = _extract_tool_call_step(event_data, emitted_tool_call_ids)
                                    if step_payload is not None:
                                        asyncio.create_task(
                                            _signal_safely(workflow_handle, "agent_status_update", arg=step_payload)
                                        )
                                if slack_turn_active[0] and _is_session_update(event_data):
                                    text_delta = _extract_agent_message_text(event_data)
                                    if text_delta:
                                        asyncio.create_task(
                                            _signal_safely(workflow_handle, "agent_text_delta", arg=text_delta)
                                        )

                            now = time.monotonic()
                            if (
                                workflow_handle is not None
                                and agent_active[0]
                                and (now - last_workflow_signal[0]) >= HEARTBEAT_INTERVAL_SECONDS
                            ):
                                last_workflow_signal[0] = now
                                try:
                                    await workflow_handle.signal("heartbeat", arg=True)
                                except Exception as e:
                                    logger.warning(
                                        "relay_workflow_heartbeat_signal_failed", run_id=run_id, error=str(e)
                                    )

                            if _is_terminal_event(event_data):
                                await redis_stream.mark_complete()
                                return

                    # SSE stream ended normally (sandbox closed connection)
                    await redis_stream.mark_complete()
                    logger.info("relay_sandbox_events_stream_closed", run_id=run_id)
                    return

            except httpx.ReadTimeout:
                reconnect_count += 1
                # May have missed an end_of_turn on the dropped stream — assume idle until re-confirmed.
                agent_active[0] = False
                logger.warning(
                    "relay_sandbox_events_read_timeout",
                    run_id=run_id,
                    reconnect_count=reconnect_count,
                )
                await asyncio.sleep(min(reconnect_count * 2, 10))

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status < 500:
                    # 4xx errors are permanent — sandbox is gone or auth is invalid
                    logger.warning(
                        "relay_sandbox_events_sandbox_gone",
                        run_id=run_id,
                        status_code=status,
                    )
                    await redis_stream.mark_error(f"Sandbox returned HTTP {status}")
                    return
                # 5xx — transient server error, worth retrying
                reconnect_count += 1
                agent_active[0] = False  # missed-end_of_turn guard (see ReadTimeout above)
                logger.warning(
                    "relay_sandbox_events_http_error",
                    run_id=run_id,
                    status_code=status,
                    error=str(e),
                    reconnect_count=reconnect_count,
                )
                await asyncio.sleep(min(reconnect_count * 2, 10))

            except (httpx.TransportError, httpx_sse.SSEError) as e:
                reconnect_count += 1
                agent_active[0] = False  # missed-end_of_turn guard (see ReadTimeout above)
                logger.warning(
                    "relay_sandbox_events_connection_error",
                    run_id=run_id,
                    error=str(e),
                    reconnect_count=reconnect_count,
                )
                await asyncio.sleep(min(reconnect_count * 2, 10))

        # Exhausted reconnect attempts
        await redis_stream.mark_error(
            f"Lost connection to sandbox after {MAX_RECONNECT_ATTEMPTS} reconnection attempts"
        )
    finally:
        stop_heartbeat.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


def _is_session_update(event_data: dict) -> bool:
    """Check if an event is a session/update notification."""
    if event_data.get("type") != "notification":
        return False
    notification = event_data.get("notification", {})
    return notification.get("method") == "session/update"


# session/update sub-types that mean the agent is actively generating. Allowlist
# (not denylist) so an unknown/missing sub-type — a future ACP lifecycle event,
# or a malformed payload — fails safe to "not active" rather than re-latching
# agent_active and reviving the idle heartbeat storm.
_GENERATION_SESSION_UPDATE_SUBTYPES = frozenset(
    {
        "agent_message",
        "agent_message_chunk",
        "agent_thought_chunk",
        "tool_call",
        "tool_call_update",
        "plan",
        "user_message",
        "user_message_chunk",
    }
)


def _is_active_agent_update(event_data: dict) -> bool:
    """True only for session/update events where the agent is actively generating."""
    if not _is_session_update(event_data):
        return False
    update = (event_data.get("notification", {}).get("params") or {}).get("update") or {}
    return update.get("sessionUpdate") in _GENERATION_SESSION_UPDATE_SUBTYPES


# Priority order for picking the plan-block step's details line from rawInput.
_TOOL_ARGS_PREVIEW_KEYS = (
    "file_path",
    "notebook_path",
    "path",
    "command",  # Bash
    "code",  # MCP exec / hogql / sql payloads
    "query",
    "pattern",
    "url",
    "description",
    "prompt",  # Task / Agent sub-agent
    "name",
    "title",
)
_TOOL_ARGS_PREVIEW_LIMIT = 240


def _extract_tool_call_step(event_data: dict, seen: set[str]) -> dict[str, Any] | None:
    """Build {title, details} from an ACP tool_call/tool_call_update.

    Streaming Claude tools arrive with empty rawInput first; we defer the
    emit + seen-write until rawInput populates so the step gets a details line.
    """
    if not _is_session_update(event_data):
        return None
    update = (event_data.get("notification", {}).get("params") or {}).get("update") or {}
    if update.get("sessionUpdate") not in ("tool_call", "tool_call_update"):
        return None

    tool_call_id = update.get("toolCallId")
    if not isinstance(tool_call_id, str) or tool_call_id in seen:
        return None

    # Bare tool name ("Read", "Bash") from agent meta; fall back to rendered title.
    meta = update.get("_meta") or {}
    title = ((meta.get("claudeCode") or {}) if isinstance(meta, dict) else {}).get("toolName")
    if not isinstance(title, str) or not title:
        title = update.get("title")
    if not isinstance(title, str) or not title:
        return None

    details = _tool_args_preview(update.get("rawInput"))
    if not details:
        # rawInput not assembled yet — next tool_call_update will retry here.
        return None

    seen.add(tool_call_id)
    return {"title": title, "details": details}


def _tool_args_preview(raw_input: Any) -> str | None:
    """First non-empty string from _TOOL_ARGS_PREVIEW_KEYS, trimmed to one line."""
    if not isinstance(raw_input, dict):
        return None
    pick: str | None = None
    for key in _TOOL_ARGS_PREVIEW_KEYS:
        value = raw_input.get(key)
        if isinstance(value, str) and value:
            pick = value
            break
    if pick is None:
        for value in raw_input.values():
            if isinstance(value, str) and value.strip():
                pick = value
                break
    if not pick:
        return None
    one_line = " ".join(pick.split())
    if len(one_line) > _TOOL_ARGS_PREVIEW_LIMIT:
        return one_line[: _TOOL_ARGS_PREVIEW_LIMIT - 1] + "…"
    return one_line


def _extract_agent_message_text(event_data: dict) -> str | None:
    """Text delta from an ACP agent_message_chunk session/update, else None."""
    notification = event_data.get("notification", {})
    if notification.get("method") != "session/update":
        return None
    params = notification.get("params") or {}
    update = params.get("update") or {}
    if update.get("sessionUpdate") != "agent_message_chunk":
        return None
    content = update.get("content")
    if not isinstance(content, dict):
        return None
    if content.get("type") != "text":
        return None
    text = content.get("text")
    return text if isinstance(text, str) and text else None


async def _signal_safely(
    workflow_handle: temporalio.client.WorkflowHandle,
    signal_name: str,
    arg: Any = None,
) -> None:
    """Fire-and-forget signal — failures must never break the relay loop."""
    try:
        if arg is None:
            await workflow_handle.signal(signal_name)
        else:
            await workflow_handle.signal(signal_name, arg=arg)
    except Exception as e:
        logger.warning("slack_app_relay_signal_failed", signal=signal_name, error=str(e))


def _is_keepalive_event(event_data: dict) -> bool:
    return event_data.get("type") == "keepalive"


_is_end_of_turn = is_turn_complete


async def _emit_agentsh_events(sandbox_id: str, run_id: str, last_ts_ns: list[int]) -> None:
    """Read recent agentsh network events and emit as debug console logs."""
    from products.tasks.backend.logic.services.agentsh import build_audit_query_command
    from products.tasks.backend.logic.services.sandbox import Sandbox
    from products.tasks.backend.temporal.observability import emit_agent_log

    try:
        sandbox = Sandbox.get_by_id(sandbox_id)
        result = await asyncio.to_thread(
            sandbox.execute,
            build_audit_query_command(since_ns=last_ts_ns[0]),
            timeout_seconds=5,
        )
        if not result.stdout.strip() or result.stdout.strip() == "[]":
            return
        events = json.loads(result.stdout)
        if not events:
            return
        last_ts_ns[0] = max(e["ts_unix_ns"] for e in events)
        lines = []
        for e in events:
            decision = (e.get("effective_decision") or "").upper()
            domain = e.get("domain") or e.get("remote") or ""
            rule = e.get("policy_rule") or ""
            if domain:
                lines.append(f"  {decision:5s} {domain} (rule: {rule})")
        if lines:
            await asyncio.to_thread(
                emit_agent_log,
                run_id,
                "debug",
                "agentsh network events:\n" + "\n".join(lines),
            )
    except Exception as e:
        logger.debug("agentsh_emit_failed", error=str(e))


def _is_terminal_event(event_data: dict) -> bool:
    """Check if an ACP event signals the agent session has ended."""
    if event_data.get("type") != "notification":
        return False
    notification = event_data.get("notification", {})
    method = notification.get("method", "")
    return method in TERMINAL_NOTIFICATION_METHODS


def _safe_dispatch_awaiting_input(task_run: TaskRunModel) -> None:
    """Schedule a push when an interactive run idles waiting on the user.

    Must be called via ``asyncio.to_thread`` (as the caller does) because the
    dispatcher performs sync I/O: a Redis write (``cache.add``) and a potential
    network call to the feature-flag service. Wrapped in a try so a failed
    dispatch never bubbles into the relay loop.
    """
    try:
        from products.tasks.backend.push_dispatcher import notify_task_run_awaiting_input

        notify_task_run_awaiting_input(task_run)
    except Exception:
        logger.warning(
            "relay_sandbox_events_push_dispatch_failed",
            run_id=str(task_run.id),
            exc_info=True,
        )


def _broker_permission_request(task_run: TaskRunModel, permission_request: dict) -> None:
    """Answer a sandbox permission request from the run's permission mode, or escalate to a human.

    A broker failure falls through to the prompt path so a broker bug degrades to
    human approval instead of a stalled agent.
    """
    try:
        if try_auto_respond_permission_request(task_run, permission_request):
            return
    except Exception:
        logger.warning(
            "relay_sandbox_events_permission_broker_failed",
            run_id=str(task_run.id),
            exc_info=True,
        )

    try:
        from products.slack_app.backend.services.agent_permissions import post_slack_permission_request_for_task_run

        post_slack_permission_request_for_task_run(task_run, permission_request)
    except Exception:
        logger.warning(
            "relay_sandbox_events_slack_permission_prompt_failed",
            run_id=str(task_run.id),
            exc_info=True,
        )
