from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction

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


@shared_task(queue=CeleryQueue.DEFAULT.value, ignore_result=True, soft_time_limit=240, time_limit=300)
@with_team_scope()
def resume_github_blocked_reports(team_id: int, after_report_id: str | None = None) -> None:
    reports = SignalReport.objects.filter(github_blocked_reports(), team_id=team_id)
    if after_report_id:
        reports = reports.filter(id__gt=after_report_id)
    if not reports.exists():
        return
    team = Team.objects.select_related("organization").get(pk=team_id)
    if not team.organization.is_ai_data_processing_approved:
        return
    if self_driving_quota_gate(team).enforced or daily_report_limit_gate(team).limited:
        return
    readiness = get_team_github_readiness(team_id, verify=True)
    if readiness.status != GitHubReadinessStatus.READY:
        return
    report_ids = list(reports.order_by("id").values_list("id", flat=True)[:RECOVERY_BATCH_SIZE])
    for report_id in report_ids:
        with transaction.atomic():
            report = (
                SignalReport.objects.select_for_update()
                .filter(github_blocked_reports(), team_id=team_id, id=report_id)
                .first()
            )
            if report is None:
                continue
            if report.status == SignalReport.Status.PENDING_INPUT:
                fields = report.transition_to(SignalReport.Status.POTENTIAL)
                fields.extend(report.transition_to(SignalReport.Status.CANDIDATE))
                report.research_blocked_reason = GitHubReadinessStatus.NOT_CONNECTED
                report.save(update_fields=[*set(fields), "research_blocked_reason"])
        async_to_sync(start_recovered_report)(team_id, str(report_id))
    if len(report_ids) == RECOVERY_BATCH_SIZE:
        resume_github_blocked_reports.apply_async(args=[team_id, str(report_ids[-1])], countdown=60)


@shared_task(queue=CeleryQueue.DEFAULT.value, ignore_result=True, soft_time_limit=60, time_limit=90)
@skip_team_scope_audit
def sweep_github_blocked_reports(after_team_id: int = 0) -> None:
    team_ids = list(
        SignalReport.objects.filter(
            research_blocked_reason__isnull=False,
            status=SignalReport.Status.CANDIDATE,
            team_id__gt=after_team_id,
        )
        .order_by("team_id")
        .values_list("team_id", flat=True)
        .distinct()[:100]
    )
    for team_id in team_ids:
        resume_github_blocked_reports.delay(team_id)
    if len(team_ids) == 100:
        sweep_github_blocked_reports.apply_async(args=[team_ids[-1]], countdown=60)
