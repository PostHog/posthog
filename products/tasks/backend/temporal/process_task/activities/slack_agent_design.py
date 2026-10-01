"""Agent-design activities: chat.startStream lifecycle (start / append / stop).

Every turn shape rides the same three-activity lifecycle. Plan-block steps, the final
answer and the turn's attachments all flow as chunks into one streamed message.
Best-effort: a Slack outage must never escalate to a task failure.
"""

from dataclasses import field
from typing import Any, Optional

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.object_tags.slack import rewrite_object_tags_for_slack
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

logger = get_logger(__name__)


@frozen
class TaskUpdateChunk:
    """One plan-block step. Flat so Temporal can serialize it."""

    id: str
    title: str
    status: str  # "in_progress" | "complete" | "error"
    details: Optional[str] = None


@frozen
class StartSlackAgentDesignStreamInput:
    slack_thread_context: dict[str, Any]
    task_updates: list[TaskUpdateChunk] = field(default_factory=list)
    first_markdown_text: Optional[str] = None
    plan_title: Optional[str] = None


@frozen
class SlackAgentDesignStream:
    ts: str
    # Whether the message has a plan block, so closing it can set the plan title.
    has_plan: bool


@frozen
class AppendSlackAgentDesignStepsInput:
    slack_thread_context: dict[str, Any]
    ts: str
    task_updates: list[TaskUpdateChunk] = field(default_factory=list)
    plan_title: Optional[str] = None


@frozen
class StopSlackAgentDesignStreamInput:
    slack_thread_context: dict[str, Any]
    ts: str
    complete_task_id: Optional[str] = None
    complete_task_title: Optional[str] = None
    # Streamed as markdown_text chunks below the plan block right before stopStream.
    final_markdown: Optional[str] = None
    # Sources the provenance footer and the run's pending attachments.
    run_id: Optional[str] = None
    # Gateway trace id of the turn being closed, so the thumbs appended to the reply
    # report against that turn.
    trace_id: Optional[str] = None
    plan_title: Optional[str] = None
    # The stream opened with the answer, which already carried the @-mention.
    mention_sent: bool = False


def _rewrite_object_tags(text: Optional[str], project_url: str) -> Optional[str]:
    """Turn the agent's object tags into the markdown links Slack can render.

    Slack renders none of the tags itself, so they have to become markdown before the text is
    posted. Rewriting rather than dropping them keeps the label the agent wrote, so a bullet
    whose only content is a citation still carries text.
    """
    if not text:
        return text
    return rewrite_object_tags_for_slack(text, project_url=project_url)


def _chunk_dicts(task_updates: list[TaskUpdateChunk]) -> list[dict[str, Any]]:
    return [{"id": t.id, "title": t.title, "status": t.status, "details": t.details} for t in task_updates]


@activity.defn
@close_db_connections
def start_slack_agent_design_stream(input: StartSlackAgentDesignStreamInput) -> Optional[SlackAgentDesignStream]:
    """Open the turn's stream and seed it. Returns None when no stream opened."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler(context)
        markdown_text = _rewrite_object_tags(input.first_markdown_text, handler.project_url)
        new_ts = handler.start_status_stream(
            task_updates=_chunk_dicts(input.task_updates),
            first_markdown_text=markdown_text,
            plan_title=input.plan_title,
        )
        return SlackAgentDesignStream(ts=new_ts, has_plan=bool(input.task_updates)) if new_ts else None
    except Exception as e:
        logger.warning("slack_app_start_agent_design_stream_failed", error=str(e))
        return None


@activity.defn
@close_db_connections
def append_slack_agent_design_steps(input: AppendSlackAgentDesignStepsInput) -> None:
    """Append plan-block step transitions and a new plan title."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler(context)
        handler.append_status_chunks(
            ts=input.ts,
            task_updates=_chunk_dicts(input.task_updates),
            plan_title=input.plan_title,
        )
    except Exception as e:
        logger.warning("slack_app_append_agent_design_steps_failed", error=str(e))


@activity.defn
@close_db_connections
def stop_slack_agent_design_stream(input: StopSlackAgentDesignStreamInput) -> None:
    """Mark the last step complete, stream the answer and the turn's attachments, close, attach files."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
    from products.tasks.backend.logic.services.living_artifacts import (
        SlackFileDeliveryResult,
        attach_streamed_slack_files,
        stream_pending_slack_attachments,
    )
    from products.tasks.backend.models import TaskRun

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler.for_run(context, input.run_id, turn_trace_id=input.trace_id)
        task_run = TaskRun.objects.get(id=input.run_id) if input.run_id else None
        deliveries: list[SlackFileDeliveryResult] = []

        def _append_attachments() -> None:
            if task_run is None:
                return
            deliveries.append(
                stream_pending_slack_attachments(
                    task_run, append_blocks=lambda blocks: handler.append_status_blocks(input.ts, blocks)
                )
            )

        handler.stop_status_stream(
            ts=input.ts,
            complete_task_id=input.complete_task_id,
            complete_task_title=input.complete_task_title,
            final_markdown=_rewrite_object_tags(input.final_markdown, handler.project_url),
            plan_title=input.plan_title,
            append_attachments=_append_attachments,
            mention_sent=input.mention_sent,
        )
        for delivery in deliveries:
            if task_run is not None:
                attach_streamed_slack_files(
                    task_run, delivery, attach_files=lambda file_ids: handler.attach_files(input.ts, file_ids)
                )
    except Exception as e:
        logger.warning("slack_app_stop_agent_design_stream_failed", error=str(e))
