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
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.rated_usage import FrozenGrantAllocation, report_trial_grant, snapshot_rated_usage

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import RatedUsageItem


def _report_day(organization_id: UUID, day: date) -> None:
    if day >= timezone.now().date():
        raise ValueError("Rated usage requires a closed UTC day")
    organization = Organization.objects.filter(id=organization_id).first()
    if organization is None:
        return
    snapshot_rated_usage(organization_id, day)
    # Snapshot the customer and amount before POST so retries survive project moves.
    deliveries = (
        SignalRatedUsage.objects.unscoped()
        .filter(organization_id=organization_id, day=day, reported_at__isnull=True)
        .order_by("team_id")
        .values("team_id", "cents", "grants")
    )
    manager = BillingManager(None)
    opened_pools: set[tuple[str, int, str]] = set()
    for batch in batched(deliveries.iterator(chunk_size=1000), 1000, strict=False):
        items: list[RatedUsageItem] = []
        for delivery in batch:
            item: RatedUsageItem = {
                "team_id": delivery["team_id"],
                "product": "inbox_usage",
                "day": day.isoformat(),
                "cents": delivery["cents"],
            }
            allocations: list[FrozenGrantAllocation] = delivery["grants"]
            for allocation in allocations:
                pool = (allocation["grant_id"], allocation["pool_cents"], allocation["pool_day"])
                if pool not in opened_pools:
                    manager.open_external_credit_pool(organization, grant_id=pool[0], cents=pool[1], day=pool[2])
                    opened_pools.add(pool)
            if allocations:
                item["grants"] = [
                    {"grant_id": allocation["grant_id"], "cents": allocation["cents"]} for allocation in allocations
                ]
            items.append(item)
        manager.record_rated_usage(organization, items)
        SignalRatedUsage.objects.unscoped().filter(
            organization_id=organization_id,
            day=day,
            team_id__in=[item["team_id"] for item in items],
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
    max_retries=5,
    soft_time_limit=60,
    time_limit=90,
)
@skip_team_scope_audit
def report_signals_trial_grant(team_id: int, grant_id: str) -> None:
    report_trial_grant(team_id, UUID(grant_id))


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
    for team_id, grant_id in (
        SignalTrialGrant.objects.unscoped()
        .filter(billing_reported_at__isnull=True, organization_id__in=Organization.objects.values("id"))
        .values_list("team_id", "id")
        .iterator(chunk_size=1000)
    ):
        report_signals_trial_grant.delay(team_id, str(grant_id))
    # Replaying closed days repairs missed deliveries; Billing deduplicates each team/day.
    begin = end - timedelta(days=1 if day else 7)
    org_days = (
        SignalSpend.objects.unscoped()
        .filter(
            Q(usage_billing=True, billing_exempt=False) | Q(trial_grant_id__isnull=False),
            finalized_at__gte=begin,
            finalized_at__lt=end,
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
