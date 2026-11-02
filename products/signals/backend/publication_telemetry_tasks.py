from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models.scoping import with_team_scope
from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.models import SignalReport
from products.signals.backend.publication_telemetry import capture_first_publication


@shared_task(
    queue=CeleryQueue.DEFAULT.value, ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5
)
@with_team_scope()
def deliver_first_publication(team_id: int, report_id: str) -> None:
    capture_first_publication(team_id, report_id)


@shared_task(queue=CeleryQueue.DEFAULT.value, ignore_result=True, soft_time_limit=60, time_limit=90)
@skip_team_scope_audit
def sweep_first_publications() -> None:
    pending = (
        SignalReport.objects.filter(first_publication_event__isnull=False, first_publication_event_sent_at__isnull=True)
        .order_by("first_visible_at", "id")
        .values_list("team_id", "id")[:100]
    )
    for team_id, report_id in pending:
        deliver_first_publication.delay(team_id, str(report_id))
