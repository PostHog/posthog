from dataclasses import dataclass
from typing import Any

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.temporal.process_task.activities.update_task_run_status import (
    TIMED_OUT_INACTIVITY_STATE_KEY,
    TIMED_OUT_WALL_CLOCK_STATE_KEY,
)
from products.tasks.backend.temporal.process_task.utils import is_bot_authorship_fallback

logger = get_logger(__name__)

SLACK_TERMINAL_NOTIFIED_STATUS_KEY = "slack_terminal_notified_status"
SLACK_TERMINAL_NOTIFIED_ERROR_KEY = "slack_terminal_notified_error_message"
SLACK_PERMISSION_REJECTION_ERROR_FRAGMENT = "[ede_diagnostic] result_type=user"
SLACK_RECOVERY_STRATEGY_KEY = "slack_recovery_strategy"
SLACK_RECOVERY_PROMPT_KEY = "slack_recovery_prompt"

SLACK_RECOVERY_STRATEGY_RETRY = "retry"
SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN = "connect_then_replan"
SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN = "unblock_and_replan"
SLACK_RECOVERY_STRATEGY_CANCELLED = "cancelled_resume"

_CONNECT_THEN_REPLAN_MARKERS = (
    "not connected",
    "connect github",
    "connect your github",
    "connect the missing",
    "missing connector",
    "missing integration",
    "github integration",
    "oauth",
    "permission scope",
    "missing scope",
    "no connected github",
    "repository selection expired",
    # Raised by the fail-closed Slack actor credential paths in
    # process_task/utils.py and sandbox_credentials.py.
    "linked github account",
    "requires an acting user",
)
_UNBLOCK_AND_REPLAN_MARKERS = (
    "infeasible",
    "cannot complete",
    "can't complete",
    "not possible",
    "missing information",
    "need more information",
    "need clarification",
    "blocked on",
    "approval request",
)

_RECOVERY_PROMPTS = {
    SLACK_RECOVERY_STRATEGY_RETRY: (
        "Reply in this thread with `retry` to try again from the latest checkpoint, "
        "or add instructions to change the approach."
    ),
    SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN: (
        "Reply after connecting the missing tool, or tell me to continue without it. "
        "I'll re-plan against the current connections before continuing."
    ),
    SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN: (
        "Reply with the missing detail or constraint. I'll re-plan with that answer before continuing."
    ),
    SLACK_RECOVERY_STRATEGY_CANCELLED: (
        "Reply in this thread when you want to resume, and include any new direction I should follow."
    ),
}

SLACK_DENIAL_STOP_MESSAGE = "Stopped after the denied action — reply here to continue with a different approach."


@dataclass
class PostSlackUpdateInput:
    run_id: str
    slack_thread_context: dict[str, Any]
    sandbox_cleaned: bool = False


@activity.defn
@close_db_connections
def post_slack_update(input: PostSlackUpdateInput) -> None:
    """Post Slack update based on current task run state. Idempotent."""
    from products.slack_app.backend.services.slack_messages import load_run_footer
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
    from products.tasks.backend.models import TaskRun

    try:
        task_run = TaskRun.objects.select_related("task", "task__created_by").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        logger.warning("post_slack_update_task_run_not_found", run_id=input.run_id)
        return

    try:
        context = SlackThreadContext.from_dict(input.slack_thread_context)
        footer = load_run_footer(task_run.id)
        handler = SlackThreadHandler(context, footer)
        # The buttons lead where the footer's links do, so they answer to the same reader.
        task_url = handler.reader_task_url()
        pr_url = (task_run.output or {}).get("pr_url")

        if input.sandbox_cleaned:
            if pr_url:
                handler.update_reaction("hedgehog")
                _post_pr_opened_notification_once(task_run, handler, pr_url, task_url)
            elif task_run.status == TaskRun.Status.CANCELLED:
                _post_cancelled_once(task_run, handler, task_url)
            elif task_run.status == TaskRun.Status.FAILED:
                _post_failure_or_timeout(task_run, handler, task_url)
            return

        if task_run.status == TaskRun.Status.COMPLETED:
            handler.update_reaction("hedgehog")
            if _is_timed_out_completion(task_run):
                handler.delete_progress()
                return
            if pr_url:
                _post_pr_opened_notification_once(task_run, handler, pr_url, task_url)
            else:
                handler.post_completion(task_url)
        elif task_run.status == TaskRun.Status.CANCELLED:
            _post_cancelled_once(task_run, handler, task_url)
        elif task_run.status == TaskRun.Status.FAILED:
            _post_failure_or_timeout(task_run, handler, task_url)
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


def _has_timeout_marker(task_run: Any) -> bool:
    """True only for runs the workflow itself terminalized as a timeout."""
    state = task_run.state if isinstance(task_run.state, dict) else {}
    return bool(state.get(TIMED_OUT_INACTIVITY_STATE_KEY) or state.get(TIMED_OUT_WALL_CLOCK_STATE_KEY))


def _is_timed_out_completion(task_run: Any) -> bool:
    """The error_message check covers COMPLETED runs finalized before the state markers existed."""
    if _has_timeout_marker(task_run):
        return True
    return bool(task_run.error_message and "timed out" in task_run.error_message)


def _post_failure_or_timeout(task_run: Any, handler: Any, task_url: str | None) -> None:
    """A genuine failure posts an error card; a timeout stays quiet (just clears progress).

    Timeouts are recorded as FAILED so the UI and analytics can tell a hang apart from a
    success, but Slack should not ping a loud error card on every timeout. Only the explicit
    state markers count here: plenty of genuine failures carry "timed out" in their message
    (sandbox request timeouts, agent command timeouts, the wizard's own deadline), and those
    still deserve an error card.
    """
    if _has_timeout_marker(task_run):
        handler.update_reaction("hedgehog")
        handler.delete_progress()
        return
    error = task_run.error_message or "Unknown error"
    _post_error_once(task_run, handler, error, task_url)


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

    # Tag the user whose request drove this run, falling back to the original
    # mentioner. ``slack_actor_slack_user_id`` is the resolved acting user — set at
    # task creation and re-stamped on resume — so a run someone else picked up pings
    # them, not the original creator. We deliberately do not consult the mapping's
    # ``latest_actor_slack_user_id``: this ping is asynchronous (it can fire long
    # after the PR opened, once the CI follow-up loop settles), so the last person to
    # touch the thread is often a casual joiner rather than the person who owns the work.
    reply_target_slack_user_id = (task_run.state or {}).get("slack_actor_slack_user_id")
    if not reply_target_slack_user_id:
        mapping = SlackThreadTaskMapping.objects.filter(task_run=task_run).first()
        reply_target_slack_user_id = mapping.mentioning_slack_user_id if mapping else None

    handler.post_pr_opened(
        pr_url,
        task_url,
        reply_target_slack_user_id=reply_target_slack_user_id,
        bot_authored=_is_bot_authored_fallback(task_run),
    )

    task_run.task.mark_slack_pr_notified(pr_url)


def _is_bot_authored_fallback(task_run: Any) -> bool:
    """Whether this pull request went out under the bot's name for want of a personal GitHub.

    Failure to answer must not cost the reader the card, so an unexpected error here means
    no hint rather than no announcement.
    """
    try:
        return is_bot_authorship_fallback(task_run.task, str(task_run.id), task_run.state)
    except Exception:
        logger.warning("post_slack_update_bot_authorship_check_failed", run_id=str(task_run.id))
        return False


def _is_terminal_notified(task_run: Any, status: str, error: str | None = None) -> bool:
    from products.tasks.backend.models import TaskRun

    state = task_run.state or {}
    if state.get(SLACK_TERMINAL_NOTIFIED_STATUS_KEY) != status:
        return False
    if status != TaskRun.Status.FAILED:
        return True
    return state.get(SLACK_TERMINAL_NOTIFIED_ERROR_KEY) == (error or "")


def _mark_terminal_notified(task_run: Any, status: str, error: str | None = None) -> None:
    from products.tasks.backend.models import TaskRun

    updates = {SLACK_TERMINAL_NOTIFIED_STATUS_KEY: status}
    if status == TaskRun.Status.FAILED:
        updates[SLACK_TERMINAL_NOTIFIED_ERROR_KEY] = error or ""
        recovery_strategy = _classify_failure_recovery(error or "")
        updates[SLACK_RECOVERY_STRATEGY_KEY] = recovery_strategy
        updates[SLACK_RECOVERY_PROMPT_KEY] = _RECOVERY_PROMPTS[recovery_strategy]
    elif status == TaskRun.Status.CANCELLED:
        updates[SLACK_RECOVERY_STRATEGY_KEY] = SLACK_RECOVERY_STRATEGY_CANCELLED
        updates[SLACK_RECOVERY_PROMPT_KEY] = _RECOVERY_PROMPTS[SLACK_RECOVERY_STRATEGY_CANCELLED]

    TaskRun.update_state_atomic(task_run.id, updates=updates)


def _classify_failure_recovery(error: str) -> str:
    normalized = error.lower()
    if any(marker in normalized for marker in _CONNECT_THEN_REPLAN_MARKERS):
        return SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN
    if any(marker in normalized for marker in _UNBLOCK_AND_REPLAN_MARKERS):
        return SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN
    return SLACK_RECOVERY_STRATEGY_RETRY


def _failure_recovery_prompt(error: str) -> str:
    return _RECOVERY_PROMPTS[_classify_failure_recovery(error)]


def _is_suppressed_permission_rejection_error(task_run: Any, error: str) -> bool:
    state = task_run.state or {}
    return bool(state.get("slack_permission_rejected")) and SLACK_PERMISSION_REJECTION_ERROR_FRAGMENT in error


def _post_error_once(task_run: Any, handler: Any, error: str, task_url: str | None) -> None:
    from products.tasks.backend.models import TaskRun

    if _is_terminal_notified(task_run, TaskRun.Status.FAILED, error):
        handler.delete_progress()
        return

    if _is_suppressed_permission_rejection_error(task_run, error):
        handler.update_reaction("hedgehog")
        handler.post_note(SLACK_DENIAL_STOP_MESSAGE)
    else:
        handler.update_reaction("x")
        handler.post_error(error, task_url, recovery_hint=_failure_recovery_prompt(error))
    _mark_terminal_notified(task_run, TaskRun.Status.FAILED, error)


def _post_cancelled_once(task_run: Any, handler: Any, task_url: str | None) -> None:
    from products.tasks.backend.models import TaskRun

    if _is_terminal_notified(task_run, TaskRun.Status.CANCELLED):
        handler.delete_progress()
        return

    handler.update_reaction("hedgehog")
    handler.post_cancelled(task_url, recovery_hint=_RECOVERY_PROMPTS[SLACK_RECOVERY_STRATEGY_CANCELLED])
    _mark_terminal_notified(task_run, TaskRun.Status.CANCELLED)


def _is_pr_opened_notified(task_run, pr_url: str) -> bool:
    # Dedupe on the Task (the conversation), not the run: a thread spans many runs
    # and a later one can re-stamp the same pr_url, so per-run state would re-announce.
    if task_run.task.slack_notified_pr_url == pr_url:
        return True
    # Transition fallback: honor the old per-run flag for runs already in flight at
    # deploy. Drop once none predate the task-level dedupe.
    legacy_state = task_run.state or {}
    if legacy_state.get("slack_pr_opened_notified"):
        legacy_url = legacy_state.get("slack_notified_pr_url")
        return not legacy_url or legacy_url == pr_url
    return False
