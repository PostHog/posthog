"""The Slack cards that follow a task's pull request through its thread.

The thread hears about a pull request through the "Pull request opened" card, and then once more
when that pull request is merged or closed on GitHub. Delivery is best-effort: the outcome is
already recorded on the run and the report.
"""

import structlog

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)


def pr_card_reply_target(task_run: TaskRun, mapping: SlackThreadTaskMapping | None) -> str | None:
    """The Slack user a PR card tags: the user whose request drove this run, else the original mentioner.

    ``slack_actor_slack_user_id`` is the resolved acting user. It is set at task creation and
    re-stamped on resume, so a run someone else picked up pings them, not the original creator.
    The mapping's ``latest_actor_slack_user_id`` is deliberately not used: PR cards post
    asynchronously (long after the request, once CI or a reviewer acts), so the last person to
    touch the thread is often a casual joiner rather than the person who owns the work.
    """
    actor = (task_run.state or {}).get("slack_actor_slack_user_id")
    if actor:
        return actor
    return mapping.mentioning_slack_user_id if mapping else None


def post_pr_closed_slack_update(run_id: str, pr_url: str, *, merged: bool = False) -> bool:
    """Post the merged or closed card once per pull request. Returns True when a card went out.

    Best-effort: any failure is logged and swallowed, and a failed card is not retried.
    """
    try:
        return _post_pr_closed_card(run_id, pr_url, merged=merged)
    except Exception:
        logger.exception("slack_pr_closed_update_failed", run_id=run_id)
        return False


def _post_pr_closed_card(run_id: str, pr_url: str, *, merged: bool) -> bool:
    task_run = TaskRun.objects.select_related("task").filter(id=run_id).first()
    if task_run is None:
        return False
    mapping = (
        SlackThreadTaskMapping.objects.filter(team_id=task_run.team_id, task_id=task_run.task_id)
        .order_by("-created_at")
        .first()
    )
    if mapping is None:
        return False
    if not task_run.task.claim_slack_pr_closed_notification(pr_url, merged=merged):
        return False

    handler = SlackThreadHandler.for_run(SlackThreadContext.from_mapping(mapping), task_run.id)
    posted = handler.post_pr_closed(
        pr_url,
        handler.reader_task_url(),
        reply_target_slack_user_id=pr_card_reply_target(task_run, mapping),
        merged=merged,
    )
    if posted:
        logger.info("slack_pr_closed_notified", run_id=str(task_run.id), task_id=str(task_run.task_id), merged=merged)
    return posted
