"""Agent-design activities: chat.startStream lifecycle + setup-phase setStatus.

All best-effort — a Slack outage must never escalate to a task failure.
"""

from dataclasses import dataclass
from typing import Any, Optional

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

logger = get_logger(__name__)


@dataclass
class TaskUpdateChunk:
    """One step in a plan-block transition. Flat so Temporal can serialize it
    without pulling Slack SDK types into the workflow sandbox."""

    id: str
    title: str
    status: str  # "in_progress" | "complete"
    details: Optional[str] = None


@dataclass
class StartSlackAgentDesignStreamInput:
    slack_thread_context: dict[str, Any]
    first_task_id: str
    first_task_title: str
    first_task_details: Optional[str] = None


@dataclass
class AppendSlackAgentDesignStepInput:
    slack_thread_context: dict[str, Any]
    ts: str
    task_updates: list[TaskUpdateChunk]
    markdown_text: Optional[str] = None


@dataclass
class StopSlackAgentDesignStreamInput:
    slack_thread_context: dict[str, Any]
    ts: str
    complete_task_id: Optional[str] = None
    complete_task_title: Optional[str] = None
    complete_task_details: Optional[str] = None


@activity.defn
@close_db_connections
def start_slack_agent_design_stream(input: StartSlackAgentDesignStreamInput) -> Optional[str]:
    """Open a streaming status message. None on failure → relay skips this turn."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        return SlackThreadHandler(context).start_status_stream(
            first_task_id=input.first_task_id,
            first_task_title=input.first_task_title,
            first_task_details=input.first_task_details,
        )
    except Exception as e:
        logger.warning("slack_app_start_agent_design_stream_failed", error=str(e))
        return None


@activity.defn
@close_db_connections
def append_slack_agent_design_step(input: AppendSlackAgentDesignStepInput) -> None:
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        SlackThreadHandler(context).append_status_chunks(
            ts=input.ts,
            task_updates=[
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "details": t.details,
                }
                for t in input.task_updates
            ],
            markdown_text=input.markdown_text,
        )
    except Exception as e:
        logger.warning("slack_app_append_agent_design_step_failed", error=str(e))


@activity.defn
@close_db_connections
def stop_slack_agent_design_stream(input: StopSlackAgentDesignStreamInput) -> None:
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        SlackThreadHandler(context).stop_status_stream(
            ts=input.ts,
            complete_task_id=input.complete_task_id,
            complete_task_title=input.complete_task_title,
            complete_task_details=input.complete_task_details,
        )
    except Exception as e:
        logger.warning("slack_app_stop_agent_design_stream_failed", error=str(e))
