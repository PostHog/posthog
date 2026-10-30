from django.db.models import Q
from django.utils import timezone

from celery import Task, shared_task

from posthog.celery_queues import CeleryQueue
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import with_team_scope
from posthog.scoping_audit import skip_team_scope_audit
from posthog.transactional_email import TransactionalEmailRetryableError, is_transactional_email_configured

from products.signals.backend.first_report_notification import deliver_first_report_email
from products.signals.backend.models import SignalFirstReportNotification


@shared_task(
    bind=True,
    queue=CeleryQueue.EMAIL.value,
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
def dispatch_first_report_notification(self: Task, team_id: int) -> None:
    try:
        deliver_first_report_email(team_id)
    except Exception as error:
        capture_exception(error)
        if isinstance(error, TransactionalEmailRetryableError) and error.retry_after is not None:
            raise self.retry(exc=error, countdown=error.retry_after)
        raise


def _sweep_first_report_notifications(after_id: str | None) -> None:
    if not is_cloud() or not is_transactional_email_configured():
        return
    pending = (
        SignalFirstReportNotification.objects.unscoped()
        .filter(queued_at__isnull=True, cancelled_at__isnull=True, send_started_at__isnull=True)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
    )
    if after_id:
        pending = pending.filter(id__gt=after_id)
    page = list(pending.order_by("id").values_list("id", "team_id")[:500])
    for _, team_id in page:
        dispatch_first_report_notification.delay(team_id)
    if len(page) == 500:
        sweep_first_report_notifications.delay(str(page[-1][0]))


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sweep_first_report_notifications(after_id: str | None = None) -> None:
    try:
        _sweep_first_report_notifications(after_id)
    except Exception as error:
        capture_exception(error)
        raise
