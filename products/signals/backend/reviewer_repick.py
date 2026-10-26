"""Restart research on a report so it picks reviewers again, after its last reviewer declined it.

The run is an ordinary re-research: it reuses the report's earlier findings, and it applies the
report's reviewer corrections, so the person who declined is not picked again. It can also rewrite
the title and summary, like any other re-research.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models.team.team import Team
from posthog.temporal.common.client import async_connect

from products.signals.backend.assignment_flags import assignment_writer_enabled
from products.signals.backend.daily_limit import daily_report_limit_gate
from products.signals.backend.enums import ReviewerRepick
from products.signals.backend.models import SignalReport
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.report_content_gates import team_research_reviewer_selection_enabled
from products.signals.backend.supersession import pending_replacement
from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow
from products.signals.backend.temporal.types import IMPLEMENTATION_DEBOUNCE_SECONDS, SignalReportSummaryWorkflowInputs

logger = structlog.get_logger(__name__)

# A report in any other live status is already researching, and that run picks reviewers itself.
REPICKABLE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT})


def request_reviewer_repick(*, team: Team, report_id: str) -> ReviewerRepick:
    """Start research for the report, or say why it cannot start. Never raises for a failed start."""
    # Evidence-based selection is what makes a re-pick worth a research run. Without the writer,
    # the run would also not be bound by the decliner's correction.
    if not (assignment_writer_enabled(team.id) and team_research_reviewer_selection_enabled(team.id)):
        return ReviewerRepick.UNAVAILABLE
    if self_driving_quota_gate(team).enforced or daily_report_limit_gate(team).limited:
        return ReviewerRepick.UNAVAILABLE
    if pending_replacement(team.id, report_id) is not None:
        return ReviewerRepick.UNAVAILABLE

    with transaction.atomic():
        report = SignalReport.objects.select_for_update().filter(team_id=team.id, id=report_id).first()
        if report is None or report.status not in REPICKABLE_STATUSES or report.signal_count < 1:
            return ReviewerRepick.UNAVAILABLE
        previous_status = report.status
        previous_promoted_at = report.promoted_at
        update_fields: set[str] = set()
        if report.status != SignalReport.Status.READY:
            update_fields.update(report.transition_to(SignalReport.Status.POTENTIAL))
        update_fields.update(report.transition_to(SignalReport.Status.CANDIDATE))
        report.save(update_fields=update_fields)
        promoted_at = report.promoted_at

    workflow_id = SignalReportSummaryWorkflow.workflow_id_for(team.id, report_id)
    try:
        async_to_sync(_start_research)(team.id, report_id, workflow_id)
    except WorkflowAlreadyStartedError:
        # A summary workflow can outlive its research while it waits to start implementation.
        # That run will not research again, so put the report back.
        _restore_status(team.id, report_id, promoted_at, previous_status, previous_promoted_at)
        return ReviewerRepick.UNAVAILABLE
    except Exception:
        logger.exception("signals.reviewer_repick.start_failed", team_id=team.id, report_id=report_id)
        if async_to_sync(_research_may_be_running)(workflow_id):
            # A candidate with no run is safe: the next matching signal promotes it again.
            return ReviewerRepick.STARTED
        _restore_status(team.id, report_id, promoted_at, previous_status, previous_promoted_at)
        return ReviewerRepick.UNAVAILABLE
    return ReviewerRepick.STARTED


async def _start_research(team_id: int, report_id: str, workflow_id: str) -> None:
    client = await async_connect()
    await client.start_workflow(
        SignalReportSummaryWorkflow.run,
        SignalReportSummaryWorkflowInputs(team_id=team_id, report_id=report_id),
        id=workflow_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        execution_timeout=timedelta(hours=1, seconds=IMPLEMENTATION_DEBOUNCE_SECONDS),
    )


async def _research_may_be_running(workflow_id: str) -> bool:
    try:
        client = await async_connect()
        description = await client.get_workflow_handle(workflow_id).describe()
    except Exception:
        # A start that timed out can still have started. Restoring the status under a live run
        # would break the run's own transitions, so an unknown state counts as running.
        return True
    return description.status == WorkflowExecutionStatus.RUNNING


def _restore_status(
    team_id: int,
    report_id: str,
    promoted_at: datetime | None,
    previous_status: str,
    previous_promoted_at: datetime | None,
) -> None:
    with transaction.atomic():
        current = SignalReport.objects.select_for_update().filter(team_id=team_id, id=report_id).first()
        # Only undo our own promotion. A signal can promote the report again in the meantime.
        if current is None or current.status != SignalReport.Status.CANDIDATE or current.promoted_at != promoted_at:
            return
        current.status = previous_status
        current.promoted_at = previous_promoted_at
        current.save(update_fields=["status", "promoted_at"])
