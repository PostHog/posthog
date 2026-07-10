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

from posthog.security.outbound_proxy import internal_httpx_async_client
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

    Stateful per run: a turn is bracketed from the first ``session/update`` after a user
    ``session/prompt`` until the turn-complete notification, and tool-call ids are de-duplicated
    for the lifetime of the run (the set is not cleared between turns). The inline fan-out in
    ``relay_sandbox_events._relay_loop`` shares this bracketing but still opens on any
    ``session/update`` — it needs the same prompt gate to stop trailing updates opening phantom turns.
    """

    def __init__(
        self,
        slack_thread_context: dict[str, Any] | None,
        turn_active: bool = False,
        awaiting_turn: bool = True,
    ) -> None:
        self._slack_thread_context = slack_thread_context or {}
        # Seeded on a resumed activity attempt so a retry landing mid-turn doesn't re-open the turn.
        self._turn_active = turn_active
        # A turn opens only once a user prompt has been seen while idle. Armed for the run's first
        # turn, then re-armed by each ``session/prompt`` observed between turns, so a trailing
        # ``session/update`` emitted after turn-complete can't open a phantom turn. A resumed attempt
        # starts disarmed and waits for the next prompt.
        self._awaiting_turn = awaiting_turn
        self._emitted_tool_call_ids: set[str] = set()

    @property
    def turn_active(self) -> bool:
        return self._turn_active

    def process(self, event_data: dict) -> list[tuple[str, Any]]:
        """Return the ordered ``(signal_name, arg)`` pairs to send for one event."""
        # A prompt received between turns arms the next turn; one received mid-turn belongs to the
        # turn already open (the stream can interleave it just after the first response event).
        if _is_session_prompt(event_data):
            if not self._turn_active:
                self._awaiting_turn = True
            return []

        if is_turn_complete(event_data):
            if self._turn_active:
                self._turn_active = False
                return [("turn_completed", None)]
            return []

        signals: list[tuple[str, Any]] = []
        if not self._turn_active and self._awaiting_turn and _is_session_update(event_data):
            self._turn_active = True
            self._awaiting_turn = False
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


def _event_method(event_data: dict) -> str | None:
    """ACP notification method for the event, for tracing (e.g. ``session/update``)."""
    notification = event_data.get("notification")
    if isinstance(notification, dict):
        return notification.get("method")
    return None


def _is_session_prompt(event_data: dict) -> bool:
    """Whether the event is a user ``session/prompt`` — the start of a new conversational turn."""
    return _event_method(event_data) == "session/prompt"


def _resume_position() -> tuple[str | None, bool]:
    """Recover ``(last-processed SSE id, turn-active)`` from a prior attempt's heartbeat details.

    On an activity retry Temporal replays ``heartbeat_details`` from the last heartbeat, letting the
    new attempt resume the SSE read past what it already relayed instead of re-reading the stream
    from ``0`` — which would re-emit ``turn_started`` for turns already delivered to Slack. The
    turn-active flag seeds the fresh emitter so a retry landing mid-turn doesn't re-open the turn on
    the first resumed ``session/update``.
    """
    details = activity.info().heartbeat_details
    last_event_id = details[0] if details and isinstance(details[0], str) and details[0] else None
    turn_active = bool(details[1]) if len(details) > 1 else False
    return last_event_id, turn_active


def _stream_via_proxy_enabled(task_run: TaskRunModel) -> bool:
    """Whether the read-via-proxy flag (``tasks-stream-via-proxy``) is on for this run.

    Mirrors the UI's ``resolve_stream_base_url`` and event_ingest's push gate so the relay reads
    the proxy leg only when the browser would too — a runtime kill-switch for both. Fails closed.
    """
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

    # Read the live proxy leg only when a proxy is configured AND the read-via-proxy flag is on for
    # the run — the same decision the task UI makes. Otherwise tail the Django-side Redis stream.
    base_url = _agent_proxy_base_url()
    task_run: TaskRunModel | None = None
    stream_via_proxy = False
    if base_url:
        task_run = await TaskRunModel.objects.select_related("task__created_by", "team").aget(id=input.run_id)
        # feature_enabled can block on a cold flag cache — off the event loop, this is an async activity.
        stream_via_proxy = await asyncio.to_thread(_stream_via_proxy_enabled, task_run)

    logger.info(
        "relay_agent_design_signals_started",
        run_id=input.run_id,
        leg="proxy" if stream_via_proxy else "redis",
        base_url=base_url,
        stream_via_proxy=stream_via_proxy,
    )

    if base_url and stream_via_proxy and task_run is not None:
        await _relay_from_agent_proxy(base_url, task_run, input, workflow_handle)
        return
    # The Redis leg reads from 0 with a fresh emitter — no resume, so no turn to carry over.
    await _relay_from_redis(input, SlackAgentDesignSignalEmitter(input.slack_thread_context), workflow_handle)


async def _relay_from_agent_proxy(
    base_url: str,
    task_run: TaskRunModel,
    input: RelayAgentDesignSignalsInput,
    workflow_handle: Any,
) -> None:
    """Consume the run's live agent-proxy SSE stream and drive the Slack signals.

    Reconnects with ``Last-Event-ID`` on transient drops and proxy stream rotations, and stops on
    the terminal ``stream-end`` frame. ``Heartbeater`` keeps the activity alive through quiet turns,
    where the proxy's keepalive comments yield no SSE events to heartbeat on. Best-effort.
    """
    events_url = f"{base_url.rstrip('/')}/v1/runs/{input.run_id}/stream"

    async with Heartbeater() as heartbeater:
        # Resume past what a prior attempt already relayed rather than replaying the stream from 0,
        # seeding the emitter's turn state so a retry mid-turn doesn't re-open the turn. A resume
        # starts disarmed (awaiting_turn=False) and waits for the next prompt, since any turn already
        # under way was open before the crash.
        last_event_id, turn_active = _resume_position()
        emitter = SlackAgentDesignSignalEmitter(
            input.slack_thread_context, turn_active=turn_active, awaiting_turn=last_event_id is None
        )
        if last_event_id:
            heartbeater.details = (last_event_id, turn_active)
            logger.info(
                "relay_agent_design_signals_resumed",
                run_id=input.run_id,
                last_event_id=last_event_id,
                turn_active=turn_active,
            )
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
                # internal_httpx_async_client bypasses the egress proxy, which denies the
                # in-cluster agent-proxy (a private-range host) with 407.
                async with internal_httpx_async_client(
                    timeout=httpx.Timeout(
                        connect=SSE_CONNECT_TIMEOUT_SECONDS,
                        read=SSE_READ_TIMEOUT_SECONDS,
                        write=30.0,
                        pool=30.0,
                    ),
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
                            signals = emitter.process(event_data)
                            # Temporary trace to pin the duplicate-turn cause: a repeated turn from a
                            # replay shows the same event_id twice; a trailing event shows a distinct id.
                            logger.info(
                                "relay_agent_design_event",
                                run_id=input.run_id,
                                event_id=sse_event.id,
                                method=_event_method(event_data),
                                signals=[name for name, _ in signals],
                            )
                            for signal_name, arg in signals:
                                await _signal_safely(workflow_handle, signal_name, arg)
                            # Checkpoint only after the event is fully relayed, so a retry resumes past
                            # it with the matching turn state rather than re-opening a delivered turn.
                            if sse_event.id:
                                heartbeater.details = (last_event_id, emitter.turn_active)
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
    """Fallback: tail the Django-side Redis stream. Works without a proxy, but arrives batched.

    Unlike the proxy leg this reads from ``0`` each attempt without heartbeat-based resume: it is the
    local/no-proxy path, so the retry replay the resume guards against is not worth the plumbing here.
    """
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
