from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.stream.redis_stream import (
    TaskRunRedisStream,
    TaskRunStreamError,
    get_task_run_stream_key,
)
from products.tasks.backend.models import TaskRun as TaskRunModel

from ee.hogai.sandbox import is_turn_complete

# Reuse the ACP event helpers and signal dispatcher from relay_sandbox_events so the SSE relay
# and this stream-tailing relay derive and emit signals from identical logic. Only the event
# source differs.
from .relay_sandbox_events import (
    _extract_agent_message_text,
    _extract_tool_call_step,
    _is_session_update,
    _signal_safely,
)

logger = structlog.get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30


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


@activity.defn
@close_db_connections
async def relay_agent_design_signals(input: RelayAgentDesignSignalsInput) -> None:
    """Tail the run's Redis event stream and emit the Slack agent-design per-turn signals.

    This is the sequenced-ingest counterpart to the agent-design fan-out in
    ``relay_sandbox_events``: when ``sandbox_event_ingest_enabled`` is on, the sandbox POSTs
    its events to the Django ingest endpoint (which writes them to this Redis stream) instead
    of holding an SSE connection open for the relay. Here we read that stream and drive the
    same signals, so the Slack thread streams turns on DEV/PROD just as it does locally.
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
    # Match the ingest endpoint's stream construction (default, non-dedicated client) so we
    # read from exactly the key the sandbox events are written to.
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
