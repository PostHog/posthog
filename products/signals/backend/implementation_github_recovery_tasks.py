from django.utils import timezone

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models.scoping import with_team_scope

from products.signals.backend.github_recovery import GITHUB_RECOVERY_WINDOW
from products.signals.backend.implementation_github_recovery import retry_report_implementation
from products.signals.backend.models import SignalReport


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
def retry_github_blocked_implementations(team_id: int, after_report_id: str | None = None) -> None:
    reports = SignalReport.objects.filter(team_id=team_id).filter(
        status=SignalReport.Status.READY,
        implementation_blocked_reason__isnull=False,
        implementation_blocked_at__gte=timezone.now() - GITHUB_RECOVERY_WINDOW,
    )
    if after_report_id:
        reports = reports.filter(id__gt=after_report_id)
    report_ids = list(reports.order_by("id").values_list("id", flat=True)[:25])
    for report_id in report_ids:
        retry_report_implementation(team_id, str(report_id))
    if len(report_ids) == 25:
        retry_github_blocked_implementations.delay(team_id, str(report_ids[-1]))
