from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import httpx
import httpx_sse
import structlog
import posthoganalytics
from temporalio import activity

from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.constants import STREAM_VIA_PROXY_FEATURE_FLAG
from products.tasks.backend.logic.services.connection_token import create_stream_read_token
from products.tasks.backend.logic.stream.redis_stream import (
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
)
from products.tasks.backend.models import TaskRun as TaskRunModel

from ee.hogai.sandbox import is_turn_complete

# Reuse the ACP event helpers, signal dispatcher, and SSE reconnect tuning from relay_sandbox_events
# so the two relays derive/emit signals and drive their SSE transport from identical logic.
from .relay_sandbox_events import (
    MAX_RECONNECT_ATTEMPTS,
    SSE_CONNECT_TIMEOUT_SECONDS,
    SSE_READ_TIMEOUT_SECONDS,
    _extract_agent_message_text,
    _extract_tool_call_step,
    _is_session_update,
    _signal_safely,
)

logger = structlog.get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30
# Terminal SSE frame name emitted when the run's stream is complete (matches the stream endpoints).
STREAM_END_EVENT_NAME = "stream-end"


class SlackAgentDesignSignalEmitter:
    """Converts a run's sandbox ACP event stream into the per-turn signals that drive
    ``SlackAgentDesignRelayWorkflow`` on the parent ``ProcessTaskWorkflow``.

    Stateful per run: a turn is bracketed from the first ``session/update`` until the
    turn-complete notification, and tool-call ids are de-duplicated for the lifetime of the
    run (the set is not cleared between turns). This mirrors the inline fan-out in
    ``relay_sandbox_events._relay_loop`` — keep the two in sync.
    """

    def __init__(self, slack_thread_context: dict[str, Any] | None) -> None:
        self._slack_thread_context = slack_thread_context or {}
        self._turn_active = False
        self._emitted_tool_call_ids: set[str] = set()

    def process(self, event_data: dict) -> list[tuple[str, Any]]:
        """Return the ordered ``(signal_name, arg)`` pairs to send for one event."""
        if is_turn_complete(event_data):
            if self._turn_active:
                self._turn_active = False
                return [("turn_completed", None)]
            return []

        signals: list[tuple[str, Any]] = []
        if not self._turn_active and _is_session_update(event_data):
            self._turn_active = True
            signals.append(("turn_started", {"slack_thread_context": self._slack_thread_context}))

        if self._turn_active:
            step_payload = _extract_tool_call_step(event_data, self._emitted_tool_call_ids)
            if step_payload is not None:
                signals.append(("agent_status_update", step_payload))
            if _is_session_update(event_data):
                text_delta = _extract_agent_message_text(event_data)
                if text_delta:
                    signals.append(("agent_text_delta", text_delta))

        return signals


@dataclass
class RelayAgentDesignSignalsInput:
    run_id: str
    task_id: str
    slack_thread_context: dict[str, Any] | None = None


def _agent_proxy_base_url() -> str | None:
    """Base URL for the agent-proxy stream read leg, or ``None`` to read Redis directly.

    Prefer the in-cluster URL (skips the ingress/CDN round-trip, and exists on envs without a
    public proxy FQDN), then the public URL the browser uses, then the ingest URL. The ingest URL
    is the single local opt-in — ``_is_sandbox_event_ingest_enabled`` keys off it and mprocs runs
    the proxy on :8003 — and the proxy serves ingest and stream on the same host, so it doubles as
    a read base locally.
    """
    return (
        settings.TASKS_AGENT_PROXY_INTERNAL_URL
        or settings.TASKS_AGENT_PROXY_PUBLIC_URL
        or settings.TASKS_AGENT_PROXY_INGEST_URL
    )


def _stream_via_proxy_enabled(task_run: TaskRunModel) -> bool:
    """Whether the read-via-proxy flag is on for this run.

    Mirrors the UI's ``resolve_stream_base_url`` and event_ingest's push gate so the relay reads
    the proxy leg only when the browser would too — keeping ``tasks-stream-via-proxy`` a runtime
    kill-switch for both. Local dev disables the analytics SDK, so DEBUG is the opt-in. Fails closed.
    """
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


@activity.defn
@close_db_connections
async def relay_agent_design_signals(input: RelayAgentDesignSignalsInput) -> None:
    """Relay a run's event stream into the Slack agent-design per-turn signals.

    Prefers the agent-proxy SSE leg (the live stream the task UI reads) so the Slack thread
    streams turns as they happen. When no proxy is configured — local dev, or an environment
    without a proxy FQDN — it falls back to tailing the Django-side Redis stream, which still
    works but arrives batched at turn-end behind the buffering ingress.
    """
    try:
        from posthog.temporal.common.client import async_connect

        temporal_client = await async_connect()
        workflow_id = TaskRunModel.get_workflow_id(input.task_id, input.run_id)
        workflow_handle = temporal_client.get_workflow_handle(workflow_id)
    except Exception as e:
        logger.warning("relay_agent_design_signals_handle_init_failed", run_id=input.run_id, error=str(e))
        return

    emitter = SlackAgentDesignSignalEmitter(input.slack_thread_context)

    # Read the live proxy leg only when a proxy is configured AND the read-via-proxy flag is on for
    # the run — the same decision the task UI makes — so the flag stays a runtime kill-switch. Load
    # the run only on that path; the Redis fallback doesn't need it. Otherwise tail the Redis stream.
    base_url = _agent_proxy_base_url()
    if base_url:
        task_run = await TaskRunModel.objects.select_related("task__created_by", "team").aget(id=input.run_id)
        # feature_enabled can block on a cold flag cache — off the event loop, this is an async activity.
        if await asyncio.to_thread(_stream_via_proxy_enabled, task_run):
            await _relay_from_agent_proxy(base_url, task_run, input, emitter, workflow_handle)
            return
    await _relay_from_redis(input, emitter, workflow_handle)


async def _relay_from_agent_proxy(
    base_url: str,
    task_run: TaskRunModel,
    input: RelayAgentDesignSignalsInput,
    emitter: SlackAgentDesignSignalEmitter,
    workflow_handle: Any,
) -> None:
    """Consume the run's live agent-proxy SSE stream and drive the Slack signals.

    Reconnects with ``Last-Event-ID`` on transient drops and proxy stream rotations, and stops on
    the terminal ``stream-end`` frame. ``Heartbeater`` keeps the activity alive through quiet turns,
    where the proxy's keepalive comments yield no SSE events to heartbeat on. Best-effort.
    """
    events_url = f"{base_url.rstrip('/')}/v1/runs/{input.run_id}/stream"

    async with Heartbeater():
        last_event_id: str | None = None
        reconnect_count = 0
        while True:
            # Re-mint per connection: the read token is short-lived and a run can outlast it.
            headers = {
                "Authorization": f"Bearer {create_stream_read_token(task_run)}",
                "Accept": "text/event-stream",
            }
            if last_event_id:
                headers["Last-Event-ID"] = last_event_id

            made_progress = False
            error: Exception | None = None
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        connect=SSE_CONNECT_TIMEOUT_SECONDS,
                        read=SSE_READ_TIMEOUT_SECONDS,
                        write=30.0,
                        pool=30.0,
                    )
                ) as client:
                    async with httpx_sse.aconnect_sse(client, "GET", events_url, headers=headers) as event_source:
                        event_source.response.raise_for_status()
                        async for sse_event in event_source.aiter_sse():
                            made_progress = True
                            if sse_event.id:
                                last_event_id = sse_event.id
                            if sse_event.event == STREAM_END_EVENT_NAME:
                                logger.info(
                                    "relay_agent_design_signals_stream_ended", run_id=input.run_id, reason="stream-end"
                                )
                                return
                            if not sse_event.data:
                                continue
                            try:
                                event_data = json.loads(sse_event.data)
                            except json.JSONDecodeError:
                                continue
                            for signal_name, arg in emitter.process(event_data):
                                await _signal_safely(workflow_handle, signal_name, arg)
            except (httpx.TransportError, httpx.HTTPStatusError, httpx_sse.SSEError) as e:
                error = e

            # A clean close without a stream-end frame is a proxy stream rotation — resume immediately.
            # Only consecutive no-progress attempts back off and eventually give up, so a healthy
            # long-lived stream reconnects without delay while a genuinely broken one stops.
            if made_progress:
                reconnect_count = 0
                continue
            reconnect_count += 1
            if reconnect_count > MAX_RECONNECT_ATTEMPTS:
                logger.warning(
                    "relay_agent_design_signals_proxy_gave_up",
                    run_id=input.run_id,
                    error=str(error) if error else "clean close with no events",
                )
                return
            await asyncio.sleep(min(2**reconnect_count, 30))


async def _relay_from_redis(
    input: RelayAgentDesignSignalsInput,
    emitter: SlackAgentDesignSignalEmitter,
    workflow_handle: Any,
) -> None:
    """Fallback: tail the Django-side Redis stream. Works without a proxy, but arrives batched."""
    redis_stream = TaskRunRedisStream(get_task_run_stream_key(input.run_id))
    try:
        async for item in redis_stream.read_stream_entries(
            start_id="0",
            keepalive_interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
        ):
            activity.heartbeat()
            if item is None:
                continue
            _, event_data = item
            for signal_name, arg in emitter.process(event_data):
                await _signal_safely(workflow_handle, signal_name, arg)
    except TaskRunStreamError as e:
        # The stream completed (complete/error sentinel) or timed out — nothing left to relay.
        logger.info("relay_agent_design_signals_stream_ended", run_id=input.run_id, reason=str(e))
