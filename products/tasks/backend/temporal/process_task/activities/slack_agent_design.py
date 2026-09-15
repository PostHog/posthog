"""Agent-design activities: chat.startStream lifecycle (start / append / stop).

Every turn shape rides the same three-activity lifecycle — plan-block steps,
interim narrative between them, and the final answer all flow as chunks into
one streamed message. Best-effort: a Slack outage must never escalate to a
task failure.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.temporal.slack_relay.object_tags import rewrite_object_tags_for_slack

logger = get_logger(__name__)


# Stream surfaces a relay can run. Values double as Slack's task_display_mode where
# one applies ("timeline"); "final_only" posts nothing until the turn completes.
STREAM_MODE_TIMELINE = "timeline"
STREAM_MODE_FINAL_ONLY = "final_only"

# TaskRun.state key holding the ts of the currently open agent-design reply, so
# out-of-workflow writers (living-artifact delivery) know one is open. Written on
# the first render, cleared on the closing one.
SLACK_STREAM_TS_STATE_KEY = "slack_stream_ts"

# TaskRun.state key holding blocks queued by artifact delivery for the open reply.
# The next render pops them into the message at its current end, so a chart lands
# roughly where the agent created it.
SLACK_PENDING_BLOCKS_STATE_KEY = "slack_stream_pending_blocks"


@dataclass
class TaskUpdateChunk:
    """One task-card step. Flat so Temporal can serialize it."""

    id: str
    title: str
    status: str  # "in_progress" | "complete" | "error"
    details: Optional[str] = None
    output: Optional[str] = None


@dataclass
class StreamChunk:
    """One ordered chunk for the timeline surface: exactly one of markdown prose
    or a task-card update. Ordered lists of these preserve the interleaving of
    narrative and tool calls that the flat ``task_updates`` + ``markdown_text``
    pair cannot express."""

    markdown_text: Optional[str] = None
    task_update: Optional[TaskUpdateChunk] = None


@dataclass
class CardCall:
    """One tool call inside a task card segment."""

    title: str
    details: Optional[str] = None
    output: Optional[str] = None
    failed: bool = False


@dataclass
class MessageSegment:
    """One piece of the agent-design reply, in reading order: prose, a task card
    holding a burst of tool calls, or raw blocks (delivered artifacts)."""

    kind: str  # "text" | "cards" | "blocks"
    text: Optional[str] = None
    calls: list[CardCall] = field(default_factory=list)
    complete: bool = False
    blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RenderSlackAgentDesignMessageInput:
    slack_thread_context: dict[str, Any]
    segments: list[MessageSegment] = field(default_factory=list)
    # None posts the reply; set, it chat.updates the existing one in place.
    ts: Optional[str] = None
    # The closing render marks open cards complete and appends mention/footer/feedback.
    closing: bool = False
    run_id: Optional[str] = None
    trace_id: Optional[str] = None


@dataclass
class RenderSlackAgentDesignMessageOutput:
    ts: Optional[str] = None
    # Artifact blocks popped from TaskRun.state and rendered at the message's current
    # end. The workflow appends them to its segments so later renders keep them there.
    artifact_blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StartSlackAgentDesignStreamInput:
    slack_thread_context: dict[str, Any]
    # Seed with EITHER a task_update step OR a markdown_text chunk (plan surface),
    # OR an ordered chunk list (timeline surface).
    first_task_id: Optional[str] = None
    first_task_title: Optional[str] = None
    first_task_details: Optional[str] = None
    first_markdown_text: Optional[str] = None
    ordered_chunks: list[StreamChunk] = field(default_factory=list)
    # None resolves to Slack's "plan" display, matching relays recorded before the field existed.
    task_display_mode: Optional[str] = None
    # Registers the open stream ts on TaskRun.state so artifact delivery can append
    # into it. None on relays recorded before the field existed.
    run_id: Optional[str] = None


@dataclass
class AppendSlackAgentDesignStepsInput:
    slack_thread_context: dict[str, Any]
    ts: str
    task_updates: list[TaskUpdateChunk] = field(default_factory=list)
    markdown_text: Optional[str] = None
    ordered_chunks: list[StreamChunk] = field(default_factory=list)


@frozen
class StopSlackAgentDesignStreamInput:
    slack_thread_context: dict[str, Any]
    ts: str
    complete_task_id: Optional[str] = None
    complete_task_title: Optional[str] = None
    complete_task_details: Optional[str] = None
    # Streamed as markdown_text chunks below the plan block right before stopStream.
    final_markdown: Optional[str] = None
    # Sources the provenance footer. Optional so a relay started before this field
    # existed replays cleanly — it just closes without one.
    run_id: Optional[str] = None
    # Gateway trace id of the turn being closed, so the thumbs appended to the reply
    # report against that turn.
    trace_id: Optional[str] = None


def _rewrite_object_tags(text: Optional[str], integration_id: int) -> Optional[str]:
    """Turn agent object tags into Slack-renderable markdown before the text is streamed.

    Streamed replies never pass through the relay activity, so its rewrite has to happen here
    too. A tag split across two streamed chunks stays as written; the final answer arrives whole.
    """
    from products.slack_app.backend.services.slack_messages import project_web_url

    if not text or "<" not in text:
        return text
    team_id = Integration.objects.only("team_id").get(id=integration_id).team_id
    return rewrite_object_tags_for_slack(text, project_url=project_web_url(team_id))


def _ordered_chunk_dicts(chunks: list[StreamChunk], integration_id: int) -> list[dict[str, Any]]:
    """Ordered chunks as the dicts the handler streams, with object tags rewritten in prose."""
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.task_update is not None:
            t = chunk.task_update
            out.append(
                {
                    "type": "task_update",
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "details": t.details,
                    "output": t.output,
                }
            )
        elif chunk.markdown_text:
            out.append({"type": "markdown_text", "text": _rewrite_object_tags(chunk.markdown_text, integration_id)})
    return out


def _register_open_stream(run_id: Optional[str], ts: Optional[str]) -> None:
    """Record the open stream's ts on TaskRun.state, or clear it when ``ts`` is None.

    Best-effort: artifact delivery treats a missing key as "no stream open" and
    falls back to a separate thread message.
    """
    if not run_id:
        return
    from products.tasks.backend.models import TaskRun

    def _mutate(state: dict[str, Any]) -> None:
        if ts is None:
            state.pop(SLACK_STREAM_TS_STATE_KEY, None)
        else:
            state[SLACK_STREAM_TS_STATE_KEY] = ts

    try:
        TaskRun.mutate_state_atomic(run_id, _mutate)
    except Exception:
        logger.warning("slack_app_stream_ts_state_write_failed", run_id=run_id)


def _pop_pending_artifact_blocks(run_id: Optional[str]) -> list[dict[str, Any]]:
    """Read the artifact blocks queued for the open reply. The caller acks them
    with _ack_pending_artifact_blocks only after the render carried them, so a
    failed render leaves them queued for the next one."""
    if not run_id:
        return []
    from products.tasks.backend.models import TaskRun

    try:
        state = TaskRun.objects.filter(id=run_id).values_list("state", flat=True).first() or {}
        pending = state.get(SLACK_PENDING_BLOCKS_STATE_KEY)
        return list(pending) if isinstance(pending, list) else []
    except Exception:
        logger.warning("slack_app_pending_blocks_read_failed", run_id=run_id)
        return []


def _ack_pending_artifact_blocks(run_id: str, count: int) -> None:
    from products.tasks.backend.models import TaskRun

    def _mutate(state: dict[str, Any]) -> None:
        pending = state.get(SLACK_PENDING_BLOCKS_STATE_KEY)
        if isinstance(pending, list):
            state[SLACK_PENDING_BLOCKS_STATE_KEY] = pending[count:]

    try:
        TaskRun.mutate_state_atomic(run_id, _mutate)
    except Exception:
        logger.warning("slack_app_pending_blocks_ack_failed", run_id=run_id)


def _segment_dicts(segments: list[MessageSegment], integration_id: int, closing: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for segment in segments:
        if segment.kind == "text" and segment.text:
            out.append({"kind": "text", "text": _rewrite_object_tags(segment.text, integration_id)})
        elif segment.kind == "cards" and segment.calls:
            out.append(
                {
                    "kind": "cards",
                    "complete": segment.complete or closing,
                    "calls": [
                        {"title": c.title, "details": c.details, "output": c.output, "failed": c.failed}
                        for c in segment.calls
                    ],
                }
            )
        elif segment.kind == "blocks" and segment.blocks:
            out.append({"kind": "blocks", "blocks": segment.blocks})
    return out


@activity.defn
@close_db_connections
def render_slack_agent_design_message(
    input: RenderSlackAgentDesignMessageInput,
) -> RenderSlackAgentDesignMessageOutput:
    """Post or chat.update the agent-design reply from its full segment list.

    Also carries artifact blocks queued on TaskRun.state into the message, acking
    them only once rendered. Best-effort: a Slack failure keeps the previous ts."""
    from products.slack_app.backend.services.slack_messages import load_run_footer
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        pending = _pop_pending_artifact_blocks(input.run_id)
        handler = SlackThreadHandler(context, turn_trace_id=input.trace_id)
        if input.closing:
            handler.run_footer = load_run_footer(input.run_id)
        ts = handler.render_agent_design_message(
            ts=input.ts,
            segments=_segment_dicts(input.segments, context.integration_id, input.closing),
            artifact_blocks=pending,
            closing=input.closing,
        )
        if ts is None:
            return RenderSlackAgentDesignMessageOutput(ts=input.ts)
        if input.run_id:
            if pending:
                _ack_pending_artifact_blocks(input.run_id, len(pending))
            _register_open_stream(input.run_id, None if input.closing else ts)
        return RenderSlackAgentDesignMessageOutput(ts=ts, artifact_blocks=pending)
    except Exception as e:
        logger.warning("slack_app_render_agent_design_message_failed", error=str(e))
        return RenderSlackAgentDesignMessageOutput(ts=input.ts)


@activity.defn
@close_db_connections
def start_slack_agent_design_stream(input: StartSlackAgentDesignStreamInput) -> Optional[str]:
    """Open the stream, seeded with either a first tool-call step or a first
    markdown_text chunk (pre-first-tool-call streaming). Returns ts or None."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        ts = SlackThreadHandler(context).start_status_stream(
            first_task_id=input.first_task_id,
            first_task_title=input.first_task_title,
            first_task_details=input.first_task_details,
            first_markdown_text=_rewrite_object_tags(input.first_markdown_text, context.integration_id),
            ordered_chunks=_ordered_chunk_dicts(input.ordered_chunks, context.integration_id),
            task_display_mode=input.task_display_mode or "plan",
        )
        if ts is not None:
            _register_open_stream(input.run_id, ts)
        return ts
    except Exception as e:
        logger.warning("slack_app_start_agent_design_stream_failed", error=str(e))
        return None


@activity.defn
@close_db_connections
def append_slack_agent_design_steps(input: AppendSlackAgentDesignStepsInput) -> None:
    """Append plan-block step transitions and/or a markdown_text chunk."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler(context)
        if input.ordered_chunks:
            handler.append_stream_chunks(
                ts=input.ts,
                chunks=_ordered_chunk_dicts(input.ordered_chunks, context.integration_id),
            )
            return
        handler.append_status_chunks(
            ts=input.ts,
            task_updates=[
                {"id": t.id, "title": t.title, "status": t.status, "details": t.details} for t in input.task_updates
            ],
            markdown_text=_rewrite_object_tags(input.markdown_text, context.integration_id),
        )
    except Exception as e:
        logger.warning("slack_app_append_agent_design_steps_failed", error=str(e))


@activity.defn
@close_db_connections
def stop_slack_agent_design_stream(input: StopSlackAgentDesignStreamInput) -> None:
    """Mark the last step complete, stream the final answer, append @-mention, close."""
    from products.slack_app.backend.services.slack_messages import load_run_footer
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        # Cleared before the Slack close so artifact delivery stops appending to a
        # stream that is about to stop.
        _register_open_stream(input.run_id, None)
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler(context, turn_trace_id=input.trace_id)
        handler.run_footer = load_run_footer(input.run_id)
        handler.stop_status_stream(
            ts=input.ts,
            complete_task_id=input.complete_task_id,
            complete_task_title=input.complete_task_title,
            complete_task_details=input.complete_task_details,
            final_markdown=_rewrite_object_tags(input.final_markdown, context.integration_id),
        )
    except Exception as e:
        logger.warning("slack_app_stop_agent_design_stream_failed", error=str(e))
