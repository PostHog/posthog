"""The Inbox report claim a workflow task takes when an Inbox report started its workflow."""

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from products.tasks.backend.facade import contracts
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.pr_urls import read_pr_urls

logger = structlog.get_logger(__name__)

INBOX_REPORT_CLAIM_STATE_KEY = "inbox_report_claim"


def claim_inbox_report(task: Task, inbox_report: contracts.WorkflowTaskInboxReport) -> None:
    """Claim the report for the task and record the outcome on its run.

    A report another actor already holds keeps its claim, and the task runs without one.
    """
    if inbox_report.claim_skip_reason is not None:
        _record_outcome(task, inbox_report.report_id, claimed=False, reason=inbox_report.claim_skip_reason)
        return
    # Deferred because the signals facade imports the tasks facade, which imports this module.
    from products.signals.backend.facade.api import claim_report_for_workflow_task  # noqa: PLC0415

    report_id = inbox_report.report_id
    claimed = claim_report_for_workflow_task(team_id=task.team_id, report_id=report_id, task_id=str(task.id))
    if not claimed:
        logger.info("workflow_task_inbox_report_claim_held", team_id=task.team_id, report_id=report_id)
    _record_outcome(task, report_id, claimed=claimed)


def _record_outcome(task: Task, report_id: str, *, claimed: bool, reason: str | None = None) -> None:
    run = task.latest_run
    if run is None:
        return
    outcome: dict[str, str | bool] = {"report_id": report_id, "claimed": claimed}
    if reason is not None:
        outcome["reason"] = reason
    run.state = {**(run.state or {}), INBOX_REPORT_CLAIM_STATE_KEY: outcome}
    run.save(update_fields=["state"])


def release_unused_inbox_report_claim(task_run: TaskRun) -> None:
    """A run that opened no pull request leaves the report free for anyone else to pick up."""
    claim = (task_run.state or {}).get(INBOX_REPORT_CLAIM_STATE_KEY)
    if not claim or not claim.get("claimed") or read_pr_urls(task_run.output or {}):
        return
    # Deferred because the signals facade imports the tasks facade, which imports this module.
    from products.signals.backend.facade.api import release_report_claim_of_task  # noqa: PLC0415

    try:
        release_report_claim_of_task(
            team_id=task_run.team_id, report_id=claim["report_id"], task_id=str(task_run.task_id)
        )
    except Exception:
        logger.exception(
            "workflow_task_inbox_report_claim_release_failed", team_id=task_run.team_id, run_id=str(task_run.id)
        )


@receiver(post_save, sender=TaskRun)
def release_unused_inbox_report_claim_on_end(
    sender: type[TaskRun], instance: TaskRun, created: bool, update_fields: frozenset[str] | None = None, **kwargs: Any
) -> None:
    # A signal rather than a call at each ending, because the agent, the API, cancellation and the
    # janitors each finish runs on their own path. After commit, so a release never blocks the
    # status change or the step wake.
    if created or not instance.is_terminal or (update_fields is not None and "status" not in update_fields):
        return
    transaction.on_commit(lambda: release_unused_inbox_report_claim(instance))
