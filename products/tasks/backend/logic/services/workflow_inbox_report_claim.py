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


def claim_inbox_report(task: Task, inbox_report: contracts.WorkflowTaskInboxReport, *, repository: str | None) -> None:
    """Claim the report for the task and record the outcome on its run.

    A report another actor already holds keeps its claim, and the task runs without one.
    """
    report_id = inbox_report.report_id
    skip_reason = inbox_report.claim_skip_reason
    if skip_reason is None and not repository:
        skip_reason = contracts.InboxReportClaimSkipReason.NO_REPOSITORY
    if skip_reason is None:
        # Deferred because the signals facade imports the tasks facade, which imports this module.
        from products.signals.backend.facade.api import (  # noqa: PLC0415
            ReportClaimOutcome,
            claim_report_for_workflow_task,
        )

        outcome = claim_report_for_workflow_task(team_id=task.team_id, report_id=report_id, task_id=str(task.id))
        if outcome != ReportClaimOutcome.CLAIMED:
            skip_reason = contracts.InboxReportClaimSkipReason(outcome)
    if skip_reason is not None:
        logger.info(
            "workflow_task_inbox_report_claim_skipped", team_id=task.team_id, report_id=report_id, reason=skip_reason
        )
    _record_outcome(task, report_id, skip_reason)


def _record_outcome(task: Task, report_id: str, skip_reason: contracts.InboxReportClaimSkipReason | None) -> None:
    run = task.latest_run
    if run is None:
        return
    outcome: dict[str, str | bool] = {"report_id": report_id, "claimed": skip_reason is None}
    if skip_reason is not None:
        outcome["reason"] = skip_reason
    run.state = {**(run.state or {}), INBOX_REPORT_CLAIM_STATE_KEY: outcome}
    run.save(update_fields=["state"])


def inbox_report_claim_outcome(task_run: TaskRun) -> dict[str, Any] | None:
    """The claim outcome the run recorded, for the workflow step that waits on it."""
    state = task_run.state if isinstance(task_run.state, dict) else {}
    claim = state.get(INBOX_REPORT_CLAIM_STATE_KEY)
    if not isinstance(claim, dict) or not isinstance(claim.get("report_id"), str):
        return None
    if not isinstance(claim.get("claimed"), bool):
        return None
    reason = claim.get("reason")
    return {
        "report_id": claim["report_id"],
        "claimed": claim["claimed"],
        "reason": reason if isinstance(reason, str) else None,
    }


def release_unused_inbox_report_claim(task_run: TaskRun) -> None:
    """A run that opened no pull request leaves the report free for anyone else to pick up."""
    claimed_report_id = _claimed_report_id(task_run)
    if claimed_report_id is None or read_pr_urls(task_run.output or {}):
        return
    # Deferred because the signals facade imports the tasks facade, which imports this module.
    from products.signals.backend.facade.api import release_report_claim_of_task  # noqa: PLC0415

    try:
        release_report_claim_of_task(
            team_id=task_run.team_id, report_id=claimed_report_id, task_id=str(task_run.task_id)
        )
    except Exception:
        logger.exception(
            "workflow_task_inbox_report_claim_release_failed", team_id=task_run.team_id, run_id=str(task_run.id)
        )


def _claimed_report_id(task_run: TaskRun) -> str | None:
    outcome = inbox_report_claim_outcome(task_run)
    return outcome["report_id"] if outcome and outcome["claimed"] else None


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
