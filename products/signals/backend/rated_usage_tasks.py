from datetime import UTC, date, datetime, time, timedelta
from itertools import batched
from uuid import UUID

from django.db.models import Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models import Organization
from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.models import SignalSpend
from products.signals.backend.rated_usage_models import SignalRatedUsage
from products.signals.backend.spend_billing import get_signals_spend_billing_credits_by_team

from ee.billing.billing_manager import BillingManager


def _report_day(organization_id: UUID, day: date) -> None:
    if day >= timezone.now().date():
        raise ValueError("Rated usage requires a closed UTC day")
    organization = Organization.objects.filter(id=organization_id).first()
    if organization is None:
        return
    begin = datetime.combine(day, time.min, UTC)
    credits = get_signals_spend_billing_credits_by_team(
        begin, begin + timedelta(days=1), organization_id=organization_id
    )
    SignalRatedUsage.objects.unscoped().bulk_create(
        [
            SignalRatedUsage(team_id=team_id, organization_id=organization_id, day=day, cents=cents)
            for team_id, cents in credits
        ],
        ignore_conflicts=True,
    )
    # Snapshot the customer and amount before POST so retries survive project moves.
    deliveries = (
        SignalRatedUsage.objects.unscoped()
        .filter(organization_id=organization_id, day=day)
        .order_by("team_id")
        .values_list("team_id", "cents")
    )
    # Grant allocation belongs to the trial integration. This path reports all metered usage as billable.
    items: list[dict[str, str | int]] = [
        {"team_id": team_id, "product": "inbox_usage", "day": day.isoformat(), "cents": cents}
        for team_id, cents in deliveries
    ]
    manager = BillingManager(None)
    for batch in batched(items, 1000, strict=False):
        manager.record_rated_usage(organization, list(batch))
        SignalRatedUsage.objects.unscoped().filter(
            organization_id=organization_id,
            day=day,
            team_id__in=[item["team_id"] for item in batch],
            reported_at__isnull=True,
        ).update(reported_at=timezone.now())


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
    _report_day(UUID(organization_id), date.fromisoformat(day))


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
            usage_billing=True,
            finalized_at__gte=begin,
            finalized_at__lt=end,
            billing_exempt=False,
            spend__gt=0,
        )
        .annotate(day=TruncDate("finalized_at", tzinfo=UTC))
        .values_list("team__organization_id", "day")
        .order_by()
    )
    delivery_window = Q(day__gte=begin.date())
    if day is None:
        delivery_window |= Q(reported_at__isnull=True)
    deliveries = (
        SignalRatedUsage.objects.unscoped()
        .filter(delivery_window, day__lt=end.date())
        .values_list("organization_id", "day")
        .order_by()
    )
    for organization_id, usage_day in (
        org_days.union(deliveries).order_by("team__organization_id", "day").iterator(chunk_size=1000)
    ):
        report_signals_rated_usage.delay(str(organization_id), usage_day.isoformat())
