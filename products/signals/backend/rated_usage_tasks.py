from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from django.db.models import Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.models import SignalSpend
from products.signals.backend.rated_usage import SignalsRatedUsageReporter
from products.signals.backend.rated_usage_models import SignalRatedUsage


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.USAGE_REPORTS.value,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    soft_time_limit=270,
    time_limit=300,
)
@skip_team_scope_audit
def report_signals_rated_usage(organization_id: str, day: str) -> None:
    SignalsRatedUsageReporter().report_day(UUID(organization_id), date.fromisoformat(day))


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.USAGE_REPORTS.value,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    soft_time_limit=270,
    time_limit=300,
)
@skip_team_scope_audit
def enqueue_signals_rated_usage(day: str | None = None) -> None:
    end = datetime.combine(date.fromisoformat(day) + timedelta(days=1) if day else timezone.now().date(), time.min, UTC)
    if end > timezone.now():
        raise ValueError("Rated usage requires a closed UTC day")
    # Replaying closed days repairs missed deliveries; Billing deduplicates each team/day.
    begin = end - timedelta(days=1 if day else 7)
    org_days = (
        SignalSpend.objects.unscoped()
        .filter(
            Q(team__organization__usage__signals_spend_credits__has_key="billing_start_date")
            | Q(team__organization__usage__signals_spend_credits__has_key="billing_cutover_date"),
            finalized_at__gte=begin,
            finalized_at__lt=end,
            billing_exempt=False,
            spend__gt=0,
        )
        .annotate(day=TruncDate("finalized_at", tzinfo=UTC))
        .values_list("team__organization_id", "day")
        .order_by()
    )
    deliveries = (
        SignalRatedUsage.objects.unscoped()
        .filter(day__gte=begin.date(), day__lt=end.date())
        .values_list("organization_id", "day")
        .order_by()
    )
    for organization_id, usage_day in (
        org_days.union(deliveries).order_by("team__organization_id", "day").iterator(chunk_size=1000)
    ):
        report_signals_rated_usage.delay(str(organization_id), usage_day.isoformat())
