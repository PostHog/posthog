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
    sandbox_cleaned: bool = False


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
        pr_url = (task_run.output or {}).get("pr_url")

        if input.sandbox_cleaned:
            if pr_url:
                handler.update_reaction("hedgehog")
                if _is_pr_opened_notified(task_run, pr_url):
                    handler.delete_progress()
                    return

                handler.post_pr_opened_sandbox_cleaned(pr_url, task_url)
                _mark_pr_opened_notified(task_run, pr_url)
            elif task_run.status == TaskRun.Status.CANCELLED:
                handler.update_reaction("hedgehog")
                handler.post_cancelled(task_url)
            elif task_run.status == TaskRun.Status.FAILED:
                error = task_run.error_message or "Unknown error"
                handler.update_reaction("x")
                handler.post_error(error, task_url)
            return

        if task_run.status == TaskRun.Status.COMPLETED:
            handler.update_reaction("hedgehog")
            if task_run.error_message and "timed out" in task_run.error_message:
                handler.delete_progress()
                return
            handler.post_completion(pr_url, task_url)
        elif task_run.status == TaskRun.Status.CANCELLED:
            handler.update_reaction("hedgehog")
            handler.post_cancelled(task_url)
        elif task_run.status == TaskRun.Status.FAILED:
            error = task_run.error_message or "Unknown error"
            handler.update_reaction("x")
            handler.post_error(error, task_url)
        else:
            if pr_url:
                _post_pr_opened_notification_once(task_run, handler, pr_url, task_url)
                handler.update_reaction("hedgehog")
                handler.delete_progress()
                return
            stage = _get_stage_from_status(task_run.status, task_run.stage)
            handler.post_or_update_progress(stage, task_url)
    except Exception:
        logger.exception("post_slack_update_failed", run_id=input.run_id)


def _get_stage_from_status(status: str, stage: str | None = None) -> str:
    """Map task run status to human-readable stage. Uses the run's stage field when available."""
    if stage:
        return stage

    from products.tasks.backend.models import TaskRun

    status_map: dict[str, str] = {
        TaskRun.Status.NOT_STARTED: "Starting up...",
        TaskRun.Status.QUEUED: "Queued...",
        TaskRun.Status.IN_PROGRESS: "In progress...",
    }
    return status_map.get(status, "In progress...")


def _post_pr_opened_notification_once(task_run, handler, pr_url: str, task_url: str) -> None:
    if _is_pr_opened_notified(task_run, pr_url):
        return

    handler.post_pr_opened(pr_url, task_url)

    _mark_pr_opened_notified(task_run, pr_url)


def _is_pr_opened_notified(task_run, pr_url: str) -> bool:
    state = task_run.state or {}
    if not state.get("slack_pr_opened_notified"):
        return False
    notified_url = state.get("slack_notified_pr_url")
    return notified_url == pr_url if notified_url else True


def _mark_pr_opened_notified(task_run, pr_url: str) -> None:
    from products.tasks.backend.models import TaskRun

    TaskRun.update_state_atomic(
        task_run.id,
        updates={
            "slack_pr_opened_notified": True,
            "slack_notified_pr_url": pr_url,
        },
    )
