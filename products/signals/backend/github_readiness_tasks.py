from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from asgiref.sync import async_to_sync
from celery import shared_task
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.celery_queues import CeleryQueue
from posthog.models.integration.github_readiness import GitHubReadinessStatus
from posthog.models.scoping import with_team_scope
from posthog.models.team.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.temporal.common.client import async_connect

from products.signals.backend.daily_limit import daily_report_limit_gate
from products.signals.backend.github_readiness import github_blocked_reports
from products.signals.backend.models import SignalReport
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs
from products.tasks.backend.facade.github_readiness import get_team_github_readiness

RECOVERY_BATCH_SIZE = 25


async def start_recovered_report(team_id: int, report_id: str) -> None:
    client = await async_connect()
    try:
        await client.start_workflow(
            "signal-report-summary",
            SignalReportSummaryWorkflowInputs(team_id=team_id, report_id=report_id, github_recovery=True),
            id=f"signals-report:{team_id}:{report_id}",
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=timedelta(hours=5),
        )
    except WorkflowAlreadyStartedError:
        pass


def _reopen_legacy_report(report: SignalReport, reason: GitHubReadinessStatus | None) -> None:
    fields = report.transition_to(SignalReport.Status.POTENTIAL)
    fields.extend(report.transition_to(SignalReport.Status.CANDIDATE))
    report.research_blocked_reason = reason
    # The recovery window counts from the run that hit the legacy blocker, not from the reconnect.
    report.research_blocked_at = report.last_run_at or report.created_at
    report.save(update_fields=[*set(fields), "research_blocked_reason", "research_blocked_at"])


def _keep_recovery_intent(reports: QuerySet[SignalReport], reason: GitHubReadinessStatus | None) -> None:
    """Persist a reconnect-triggered recovery that a prerequisite stopped.

    Legacy `pending_input` reports have no blocker for the sweep to select, so they move to
    candidate here. A `temporarily_unavailable` reason makes the sweep retry them. A `None` reason
    leaves them to the next matching signal or a manual rerun, which is the rule for quota pauses.
    """
    with transaction.atomic():
        for report in reports.select_for_update().filter(status=SignalReport.Status.PENDING_INPUT):
            _reopen_legacy_report(report, reason)
        reports.filter(status=SignalReport.Status.CANDIDATE).update(research_blocked_reason=reason)


@shared_task(queue=CeleryQueue.LONG_RUNNING.value, ignore_result=True, soft_time_limit=240, time_limit=300)
@with_team_scope()
def resume_github_blocked_reports(
    team_id: int, after_report_id: str | None = None, *, connection_restored: bool = False
) -> None:
    eligible = github_blocked_reports(connection_restored=connection_restored)
    reports = SignalReport.objects.filter(eligible, team_id=team_id)
    if after_report_id:
        reports = reports.filter(id__gt=after_report_id)
    if not reports.exists():
        return
    team = Team.objects.select_related("organization").get(pk=team_id)
    if self_driving_quota_gate(team).enforced:
        if connection_restored:
            _keep_recovery_intent(reports, None)
        return
    if not team.organization.is_ai_data_processing_approved or daily_report_limit_gate(team).limited:
        if connection_restored:
            _keep_recovery_intent(reports, GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE)
        return
    readiness = get_team_github_readiness(team_id, verify=True)
    if readiness.status != GitHubReadinessStatus.READY:
        if connection_restored:
            _keep_recovery_intent(reports, readiness.status)
        else:
            reports.filter(status=SignalReport.Status.CANDIDATE).update(research_blocked_reason=readiness.status)
        return
    report_ids = list(reports.order_by("id").values_list("id", flat=True)[:RECOVERY_BATCH_SIZE])
    for report_id in report_ids:
        with transaction.atomic():
            report = SignalReport.objects.select_for_update().filter(eligible, team_id=team_id, id=report_id).first()
            if report is None:
                continue
            if report.status == SignalReport.Status.PENDING_INPUT:
                _reopen_legacy_report(report, GitHubReadinessStatus.NOT_CONNECTED)
        async_to_sync(start_recovered_report)(team_id, str(report_id))
    if len(report_ids) == RECOVERY_BATCH_SIZE:
        resume_github_blocked_reports.apply_async(
            args=[team_id, str(report_ids[-1])], kwargs={"connection_restored": connection_restored}, countdown=60
        )


@shared_task(queue=CeleryQueue.DEFAULT.value, ignore_result=True, soft_time_limit=60, time_limit=90)
@skip_team_scope_audit
def sweep_github_blocked_reports(after_team_id: int = 0) -> None:
    team_ids = list(
        SignalReport.objects.filter(github_blocked_reports(), team_id__gt=after_team_id)
        .order_by("team_id")
        .values_list("team_id", flat=True)
        .distinct()[:100]
    )
    for team_id in team_ids:
        resume_github_blocked_reports.delay(team_id)
    if len(team_ids) == 100:
        sweep_github_blocked_reports.apply_async(args=[team_ids[-1]], countdown=60)
