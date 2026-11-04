from datetime import timedelta

from django.conf import settings

from asgiref.sync import async_to_sync
from celery import shared_task
from temporalio.common import WorkflowIDReusePolicy

from posthog.celery_queues import CeleryQueue
from posthog.models import Team
from posthog.models.integration.github_readiness import GitHubAccessUnavailable, GitHubReadinessStatus
from posthog.models.scoping import with_team_scope
from posthog.temporal.common.client import async_connect

from products.signals.backend.daily_limit import daily_report_limit_gate
from products.signals.backend.github_readiness import check_report_github_readiness, github_blocked_reports
from products.signals.backend.models import SignalReport
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs

RECOVERY_BATCH_SIZE = 25


async def start_recovered_report(team_id: int, report_id: str) -> None:
    client = await async_connect()
    await client.start_workflow(
        "signal-report-summary",
        SignalReportSummaryWorkflowInputs(team_id=team_id, report_id=report_id, github_recovery=True),
        id=f"signals-report:{team_id}:{report_id}",
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        execution_timeout=timedelta(hours=5),
    )


@shared_task(
    queue=CeleryQueue.LONG_RUNNING.value,
    ignore_result=True,
    soft_time_limit=240,
    time_limit=300,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=10,
    max_retries=5,
)
@with_team_scope()
def resume_github_blocked_reports(team_id: int, after_report_id: str | None = None) -> None:
    reports = SignalReport.objects.filter(github_blocked_reports(), team_id=team_id)
    if after_report_id:
        reports = reports.filter(id__gt=after_report_id)
    if not reports.exists():
        return
    team = Team.objects.select_related("organization").get(pk=team_id)
    if (
        not team.organization.is_ai_data_processing_approved
        or self_driving_quota_gate(team).enforced
        or daily_report_limit_gate(team).limited
    ):
        return
    report_ids = list(reports.order_by("id").values_list("id", flat=True)[:RECOVERY_BATCH_SIZE])
    for report_id in report_ids:
        if check_report_github_readiness(team_id, str(report_id), recovery=True):
            async_to_sync(start_recovered_report)(team_id, str(report_id))
        elif SignalReport.objects.filter(
            team_id=team_id, id=report_id, research_blocked_reason=GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE
        ).exists():
            raise GitHubAccessUnavailable(GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE)
    if len(report_ids) == RECOVERY_BATCH_SIZE:
        resume_github_blocked_reports.delay(team_id, str(report_ids[-1]))
