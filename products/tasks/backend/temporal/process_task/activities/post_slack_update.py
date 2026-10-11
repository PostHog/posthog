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
SLACK_RECOVERY_STRATEGY_WAIT_FOR_SPEND_LIMIT = "wait_for_spend_limit"
SLACK_RECOVERY_STRATEGY_RECONNECT_GITHUB = "reconnect_github"
SLACK_SPEND_LIMIT_ERROR_FRAGMENT = "this agent run reached its spend limit"

# Checked before the connect-then-replan markers, because a rejected personal credential needs
# the person to authorize again rather than a re-plan against the connections already there.
_RECONNECT_GITHUB_MARKERS = ("requires reauthorization",)

_RECONNECT_GITHUB_CONNECT_LABEL = "Connect your GitHub in PostHog settings"
_RECONNECT_GITHUB_PROMPT = (
    "Your personal GitHub connection stopped working, so this run could not use it. "
    "{connect} to authorize it again, or to connect it for the first time. "
    "Then reply in this thread and I'll pick up the new credentials."
)

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
    SLACK_RECOVERY_STRATEGY_WAIT_FOR_SPEND_LIMIT: (
        "Wait for this run's spend limit to reset before replying in the thread."
    ),
    SLACK_RECOVERY_STRATEGY_RECONNECT_GITHUB: _RECONNECT_GITHUB_PROMPT.format(connect=_RECONNECT_GITHUB_CONNECT_LABEL),
}

SLACK_DENIAL_STOP_MESSAGE = "Stopped after the denied action — reply here to continue with a different approach."


@dataclass(frozen=False)
class PostSlackUpdateInput:
    run_id: str
    slack_thread_context: dict[str, Any]
    sandbox_cleaned: bool = False


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
        handler = SlackThreadHandler.for_run(context, task_run.id)
        # The buttons lead where the footer's link does.
        task_url = handler.reader_task_url()
        pr_url = (task_run.output or {}).get("pr_url")

        if input.sandbox_cleaned:
            if pr_url:
                handler.update_reaction("hedgehog")
                _post_pr_opened_notification_once(task_run, handler, pr_url, task_url)
            elif task_run.status == TaskRun.Status.CANCELLED:
                _post_cancelled_once(task_run, handler)
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
            _post_cancelled_once(task_run, handler)
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
    from products.tasks.backend.logic.services.slack_pr_cards import pr_card_reply_target

    if _is_pr_opened_notified(task_run, pr_url):
        # Skip the repost but still clear any lingering progress marker.
        handler.delete_progress()
        return

    mapping = SlackThreadTaskMapping.objects.filter(task_run=task_run).first()
    handler.post_pr_opened(
        pr_url,
        task_url,
        reply_target_slack_user_id=pr_card_reply_target(task_run, mapping),
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
        updates[SLACK_RECOVERY_PROMPT_KEY] = _recovery_prompt(recovery_strategy, _task_run_team_id(task_run))
    elif status == TaskRun.Status.CANCELLED:
        updates[SLACK_RECOVERY_STRATEGY_KEY] = SLACK_RECOVERY_STRATEGY_CANCELLED
        updates[SLACK_RECOVERY_PROMPT_KEY] = _RECOVERY_PROMPTS[SLACK_RECOVERY_STRATEGY_CANCELLED]

    TaskRun.update_state_atomic(task_run.id, updates=updates)


def _task_run_team_id(task_run: Any) -> int | None:
    """The run's team, or None when it cannot be read.

    A prompt without a link still tells the reader what to do, so an unreadable team costs the
    link rather than the whole message.
    """
    try:
        return task_run.task.team_id
    except Exception:
        logger.warning("post_slack_update_team_id_unavailable", run_id=str(task_run.id))
        return None


def _classify_failure_recovery(error: str) -> str:
    normalized = error.lower()
    if SLACK_SPEND_LIMIT_ERROR_FRAGMENT in normalized:
        return SLACK_RECOVERY_STRATEGY_WAIT_FOR_SPEND_LIMIT
    if any(marker in normalized for marker in _RECONNECT_GITHUB_MARKERS):
        return SLACK_RECOVERY_STRATEGY_RECONNECT_GITHUB
    if any(marker in normalized for marker in _CONNECT_THEN_REPLAN_MARKERS):
        return SLACK_RECOVERY_STRATEGY_CONNECT_THEN_REPLAN
    if any(marker in normalized for marker in _UNBLOCK_AND_REPLAN_MARKERS):
        return SLACK_RECOVERY_STRATEGY_UNBLOCK_AND_REPLAN
    return SLACK_RECOVERY_STRATEGY_RETRY


def _failure_recovery_prompt(error: str, team_id: int | None = None) -> str:
    return _recovery_prompt(_classify_failure_recovery(error), team_id)


def _recovery_prompt(strategy: str, team_id: int | None) -> str:
    if strategy == SLACK_RECOVERY_STRATEGY_RECONNECT_GITHUB and team_id is not None:
        return _reconnect_github_prompt(team_id)
    return _RECOVERY_PROMPTS[strategy]


def _reconnect_github_prompt(team_id: int) -> str:
    """The reconnect prompt, linked to the settings flow.

    That one flow both reauthorizes an existing install and creates a first one, so a single
    link serves a person whose credentials expired and a person who never connected.
    """
    from products.slack_app.backend.services.slack_welcome_messages import github_connect_url

    link = f"<{github_connect_url(team_id)}|{_RECONNECT_GITHUB_CONNECT_LABEL}>"
    return _RECONNECT_GITHUB_PROMPT.format(connect=link)


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
        handler.post_error(error, task_url, recovery_hint=_failure_recovery_prompt(error, _task_run_team_id(task_run)))
    _mark_terminal_notified(task_run, TaskRun.Status.FAILED, error)


def _post_cancelled_once(task_run: Any, handler: Any) -> None:
    from products.tasks.backend.models import TaskRun

    if _is_terminal_notified(task_run, TaskRun.Status.CANCELLED):
        handler.delete_progress()
        return

    handler.update_reaction("hedgehog")
    handler.delete_progress()
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
