from __future__ import annotations

import json
import time
import asyncio
from dataclasses import dataclass

import httpx
import httpx_sse
import structlog
import temporalio.client
from temporalio import activity

from products.tasks.backend.models import TaskRun as TaskRunModel
from products.tasks.backend.services.agent_command import validate_sandbox_url
from products.tasks.backend.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.stream.redis_stream import TaskRunRedisStream, get_task_run_stream_key

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


@activity.defn
async def relay_sandbox_events(input: RelaySandboxEventsInput) -> None:
    """Long-running activity that relays SSE events from a sandbox agent to a Redis stream.

    Connects to the sandbox's GET /events SSE endpoint and writes each event
    into a per-task-run Redis stream for the Django SSE endpoint to consume.
    """
    validation_error = validate_sandbox_url(input.sandbox_url)
    if validation_error:
        raise ValueError(f"Invalid sandbox URL: {validation_error}")

    stream_key = get_task_run_stream_key(input.run_id)
    redis_stream = TaskRunRedisStream(stream_key)
    await redis_stream.initialize()

    task_run = await TaskRunModel.objects.select_related("task__created_by").aget(id=input.run_id)
    created_by = task_run.task.created_by
    connection_token = create_sandbox_connection_token(
        task_run=task_run,
        user_id=created_by.id if created_by else 0,
        distinct_id=input.distinct_id,
    )

    headers = {
        "Authorization": f"Bearer {connection_token}",
        "Accept": "text/event-stream",
    }
    params: dict[str, str] = {}
    if input.sandbox_connect_token:
        params["_modal_connect_token"] = input.sandbox_connect_token

    events_url = f"{input.sandbox_url.rstrip('/')}/events"

    try:
        await _relay_loop(
            events_url=events_url,
            headers=headers,
            params=params,
            redis_stream=redis_stream,
            run_id=input.run_id,
            task_id=input.task_id,
        )
    except asyncio.CancelledError:
        logger.info("relay_sandbox_events_cancelled", run_id=input.run_id)
        await redis_stream.mark_error("Relay cancelled")
        raise
    except Exception as e:
        logger.exception("relay_sandbox_events_failed", run_id=input.run_id, error=str(e))
        await redis_stream.mark_error(str(e)[:500])
        raise


async def _background_heartbeat(
    stop_event: asyncio.Event,
    workflow_handle: temporalio.client.WorkflowHandle | None = None,
    last_event_time: list[float] | None = None,
    last_workflow_signal: list[float] | None = None,
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
            # Lazy import to avoid circular dependency (workflow imports this module)
            from products.tasks.backend.temporal.process_task.workflow import INACTIVITY_TIMEOUT_MINUTES

            now = time.monotonic()
            if (
                workflow_handle is not None
                and last_event_time is not None
                and last_event_time[0] > 0
                and (now - last_event_time[0]) < INACTIVITY_TIMEOUT_MINUTES * 60
                and (last_workflow_signal is None or (now - last_workflow_signal[0]) >= HEARTBEAT_INTERVAL_SECONDS)
            ):
                if last_workflow_signal is not None:
                    last_workflow_signal[0] = now
                try:
                    await workflow_handle.signal("heartbeat")
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

    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _background_heartbeat(stop_heartbeat, workflow_handle, last_event_time, last_workflow_signal)
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
                        reconnect_count = 0  # Reset on successful connection
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

                            await redis_stream.write_event(event_data)
                            last_event_time[0] = time.monotonic()

                            now = time.monotonic()
                            if (
                                workflow_handle is not None
                                and (now - last_workflow_signal[0]) >= HEARTBEAT_INTERVAL_SECONDS
                            ):
                                last_workflow_signal[0] = now
                                try:
                                    await workflow_handle.signal("heartbeat")
                                except Exception as e:
                                    logger.warning(
                                        "relay_workflow_heartbeat_signal_failed", run_id=run_id, error=str(e)
                                    )

                            if _is_terminal_event(event_data):
                                await redis_stream.mark_complete()
                                return

                    # SSE stream ended normally (sandbox closed connection)
                    await redis_stream.mark_complete()
                return

            except httpx.ReadTimeout:
                reconnect_count += 1
                logger.warning(
                    "relay_sandbox_events_read_timeout",
                    run_id=run_id,
                    reconnect_count=reconnect_count,
                )
                await asyncio.sleep(min(reconnect_count * 2, 10))

            except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
                reconnect_count += 1
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


def _is_terminal_event(event_data: dict) -> bool:
    """Check if an ACP event signals the agent session has ended."""
    if event_data.get("type") != "notification":
        return False
    notification = event_data.get("notification", {})
    method = notification.get("method", "")
    return method in TERMINAL_NOTIFICATION_METHODS
