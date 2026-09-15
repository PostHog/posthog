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

# TaskRun.state key holding the ts of the currently open agent-design stream, so
# out-of-workflow writers (living-artifact delivery) can append into it. Written on
# stream start, cleared on stop.
SLACK_STREAM_TS_STATE_KEY = "slack_stream_ts"


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
