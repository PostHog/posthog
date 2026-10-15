"""The Inbox report claim a workflow task takes when an Inbox report started its workflow."""

import structlog

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.pr_urls import read_pr_urls

logger = structlog.get_logger(__name__)

INBOX_REPORT_CLAIM_STATE_KEY = "inbox_report_claim"


def claim_inbox_report(task: Task, report_id: str) -> None:
    """Claim the report for the task and record the outcome on its run.

    A report another actor already holds keeps its claim, and the task runs without one.
    """
    # Deferred because the signals facade imports the tasks facade, which imports this module.
    from products.signals.backend.facade.api import claim_report_for_workflow_task  # noqa: PLC0415

    claimed = claim_report_for_workflow_task(team_id=task.team_id, report_id=report_id, task_id=str(task.id))
    if not claimed:
        logger.info("workflow_task_inbox_report_claim_held", team_id=task.team_id, report_id=report_id)
    run = task.latest_run
    if run is None:
        return
    run.state = {**(run.state or {}), INBOX_REPORT_CLAIM_STATE_KEY: {"report_id": report_id, "claimed": claimed}}
    run.save(update_fields=["state"])


def release_unused_inbox_report_claim(task_run: TaskRun) -> None:
    """A run that opened no pull request leaves the report free for anyone else to pick up."""
    claim = (task_run.state or {}).get(INBOX_REPORT_CLAIM_STATE_KEY)
    if not claim or not claim.get("claimed") or read_pr_urls(task_run.output or {}):
        return
    # Deferred because the signals facade imports the tasks facade, which imports this module.
    from products.signals.backend.facade.api import release_report_claim_of_task  # noqa: PLC0415

    release_report_claim_of_task(team_id=task_run.team_id, report_id=claim["report_id"], task_id=str(task_run.task_id))
