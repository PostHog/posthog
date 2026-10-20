from celery import shared_task

from posthog.models.scoping import with_team_scope
from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.first_report_notification import deliver_first_report_email
from products.signals.backend.models import SignalFirstReportNotification


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    soft_time_limit=210,
    time_limit=240,
    acks_late=True,
    reject_on_worker_lost=True,
)
@with_team_scope()
def dispatch_first_report_notification(team_id: int) -> None:
    deliver_first_report_email(team_id)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sweep_first_report_notifications(after_id: str | None = None) -> None:
    pending = SignalFirstReportNotification.objects.unscoped().filter(
        queued_at__isnull=True, cancelled_at__isnull=True, send_started_at__isnull=True
    )
    if after_id:
        pending = pending.filter(id__gt=after_id)
    page = list(pending.order_by("id").values_list("id", "team_id")[:500])
    for _, team_id in page:
        dispatch_first_report_notification.delay(team_id)
    if len(page) == 500:
        sweep_first_report_notifications.delay(str(page[-1][0]))
