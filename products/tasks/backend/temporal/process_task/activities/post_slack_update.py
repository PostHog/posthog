from dataclasses import dataclass
from typing import Any

from django.conf import settings

from temporalio import activity

from posthog.models.user import User
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.access import has_tasks_access

logger = get_logger(__name__)


@dataclass
class PostSlackUpdateInput:
    run_id: str
    slack_thread_context: dict[str, Any]
    sandbox_cleaned: bool = False


def _viewer_has_posthog_code_access(viewer: User | None) -> bool:
    """Fail closed: missing creator or any flag-service error suppresses the link.

    The PostHog Code app is rolled out via cohort + invite redemption; surfacing
    deep links to users who can't open them sends them into an install flow we
    don't want to scale right now. Errors from the flag service therefore default
    to "no access" rather than "show the link anyway".
    """
    if viewer is None:
        return False
    try:
        return has_tasks_access(viewer)
    except Exception:
        logger.exception("post_slack_update_access_check_failed", user_id=getattr(viewer, "id", None))
        return False


@activity.defn
@close_db_connections
def post_slack_update(input: PostSlackUpdateInput) -> None:
    """Post Slack update based on current task run state. Idempotent."""
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
    from products.tasks.backend.models import TaskRun

    try:
        task_run = TaskRun.objects.select_related("task", "task__created_by").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        logger.warning("post_slack_update_task_run_not_found", run_id=input.run_id)
        return

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        handler = SlackThreadHandler(context)
        creator_has_access = _viewer_has_posthog_code_access(task_run.task.created_by)
        task_url: str | None = (
            f"{settings.SITE_URL}/project/{task_run.task.team_id}/tasks/{task_run.task_id}?runId={task_run.id}"
            if creator_has_access
            else None
        )
        pr_url = (task_run.output or {}).get("pr_url")

        if input.sandbox_cleaned:
            if pr_url:
                handler.update_reaction("hedgehog")
                _post_pr_opened_notification_once(task_run, handler, pr_url, task_url)
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
            if pr_url:
                _post_pr_opened_notification_once(task_run, handler, pr_url, task_url)
            else:
                handler.post_completion(task_url)
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
                # Task is still running (PR opened mid-run) — keep the :eyes: reaction
                # so the thread reads as in-progress until it genuinely completes.
                handler.update_reaction("eyes")
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


def _post_pr_opened_notification_once(
    task_run,
    handler,
    pr_url: str,
    task_url: str | None,
) -> None:
    from products.slack_app.backend.models import SlackThreadTaskMapping

    if _is_pr_opened_notified(task_run, pr_url):
        # Skip the repost but still clear any lingering progress marker.
        handler.delete_progress()
        return

    # Resolve the reply target from the live mapping so the PR notification
    # tags the current actor instead of the thread starter.
    mapping = SlackThreadTaskMapping.objects.filter(task_run=task_run).first()
    reply_target_slack_user_id = (
        (mapping.latest_actor_slack_user_id or mapping.mentioning_slack_user_id) if mapping else None
    )

    handler.post_pr_opened(pr_url, task_url, reply_target_slack_user_id=reply_target_slack_user_id)

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
