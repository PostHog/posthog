"""Tell a task's Slack thread that the pull request it announced was closed without merging.

The thread hears about a pull request once, through the "Pull request opened" card. When a person
closes that pull request on GitHub, this posts the matching close in the same thread. Delivery is
best-effort: the close is already recorded on the run and the report.
"""

import structlog

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import load_run_footer
from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)


def post_pr_closed_slack_update(run_id: str, pr_url: str) -> bool:
    """Post the close card once per pull request. Returns True when a card went out."""
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
    if not task_run.task.claim_slack_pr_closed_notification(pr_url):
        return False

    context = SlackThreadContext(
        integration_id=mapping.integration_id,
        channel=mapping.channel,
        thread_ts=mapping.thread_ts,
        mentioning_slack_user_id=mapping.mentioning_slack_user_id,
    )
    handler = SlackThreadHandler(context, load_run_footer(task_run.id, integration_id=mapping.integration_id))
    # Same target as the "Pull request opened" card, so the person who owns the work hears both.
    reply_target_slack_user_id = (task_run.state or {}).get("slack_actor_slack_user_id") or (
        mapping.mentioning_slack_user_id
    )
    handler.post_pr_closed(pr_url, handler.reader_task_url(), reply_target_slack_user_id=reply_target_slack_user_id)
    logger.info("slack_pr_closed_notified", run_id=str(task_run.id), task_id=str(task_run.task_id))
    return True
