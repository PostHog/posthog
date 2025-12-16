from dataclasses import dataclass
from typing import Any

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PostSlackUpdateInput:
    run_id: str
    slack_thread_context: dict[str, Any]


@activity.defn
def post_slack_update(input: PostSlackUpdateInput) -> None:
    """Post Slack update based on current task run state. Idempotent."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
    from products.tasks.backend.models import TaskRun

    try:
        task_run = TaskRun.objects.select_related("task").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        logger.warning("post_slack_update_task_run_not_found", run_id=input.run_id)
        return

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler(context)
        task_url = f"{settings.SITE_URL}/project/{task_run.task.team_id}/tasks/{task_run.task_id}?runId={task_run.id}"

        if task_run.status == TaskRun.Status.COMPLETED:
            pr_url = (task_run.output or {}).get("pr_url")
            handler.post_completion(pr_url, task_url)
        elif task_run.status == TaskRun.Status.FAILED:
            error = task_run.error_message or "Unknown error"
            handler.post_error(error, task_url)
        else:
            stage = _get_stage_from_status(task_run.status)
            handler.post_or_update_progress(stage, task_url)
    except Exception:
        logger.exception("post_slack_update_failed", run_id=input.run_id)


def _get_stage_from_status(status: str) -> str:
    """Map task run status to human-readable stage."""
    from products.tasks.backend.models import TaskRun

    status_map: dict[str, str] = {
        TaskRun.Status.NOT_STARTED: "In progress...",
        TaskRun.Status.QUEUED: "In progress...",
        TaskRun.Status.IN_PROGRESS: "In progress...",
    }
    return status_map.get(status, "In progress...")
