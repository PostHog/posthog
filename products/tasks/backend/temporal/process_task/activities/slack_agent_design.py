"""Agent-design activities: chat.startStream lifecycle (start / append / stop).

Every turn shape rides the same three-activity lifecycle — plan-block steps,
interim narrative between them, and the final answer all flow as chunks into
one streamed message. Best-effort: a Slack outage must never escalate to a
task failure.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from temporalio import activity

from posthog.models.integration import Integration
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.temporal.slack_relay.object_tags import rewrite_object_tags_for_slack

logger = get_logger(__name__)


@dataclass
class TaskUpdateChunk:
    """One plan-block step. Flat so Temporal can serialize it."""

    id: str
    title: str
    status: str  # "in_progress" | "complete"
    details: Optional[str] = None


@dataclass
class StartSlackAgentDesignStreamInput:
    slack_thread_context: dict[str, Any]
    # Seed with EITHER a task_update step OR a markdown_text chunk.
    first_task_id: Optional[str] = None
    first_task_title: Optional[str] = None
    first_task_details: Optional[str] = None
    first_markdown_text: Optional[str] = None


@dataclass
class AppendSlackAgentDesignStepsInput:
    slack_thread_context: dict[str, Any]
    ts: str
    task_updates: list[TaskUpdateChunk] = field(default_factory=list)
    markdown_text: Optional[str] = None


@dataclass
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


@activity.defn
@close_db_connections
def start_slack_agent_design_stream(input: StartSlackAgentDesignStreamInput) -> Optional[str]:
    """Open the stream, seeded with either a first tool-call step or a first
    markdown_text chunk (pre-first-tool-call streaming). Returns ts or None."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        return SlackThreadHandler(context).start_status_stream(
            first_task_id=input.first_task_id,
            first_task_title=input.first_task_title,
            first_task_details=input.first_task_details,
            first_markdown_text=_rewrite_object_tags(input.first_markdown_text, context.integration_id),
        )
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
        SlackThreadHandler(context).append_status_chunks(
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
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler(context)
        # Describing the run costs a query and a flag call, so only do it for a
        # workspace that will actually be shown the result.
        if handler.footer_enabled():
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
