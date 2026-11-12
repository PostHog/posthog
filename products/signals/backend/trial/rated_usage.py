from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from itertools import groupby
from typing import TypedDict
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models import Organization

from products.signals.backend.rated_usage_models import SignalRatedUsage
from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.usage import daily_spend

from ee.billing.billing_manager import BillingManager


class FrozenGrantAllocation(TypedDict):
    grant_id: str
    cents: int
    pool_cents: int
    pool_day: str


def trial_pool_id(grant: SignalTrialGrant) -> str:
    return f"signals-trial-{grant.id}"


def trial_pool_cents(grant: SignalTrialGrant) -> int:
    return (grant.allowance_microusd + 9_999) // 10_000


def report_trial_grant(team_id: int, grant_id: UUID) -> None:
    grant = (
        SignalTrialGrant.objects.for_team(team_id, canonical=True)
        .filter(id=grant_id, billing_reported_at__isnull=True)
        .first()
    )
    if grant is None:
        return
    organization = Organization.objects.filter(id=grant.organization_id).first()
    if organization is None:
        return
    BillingManager(None).open_external_credit_pool(
        organization,
        grant_id=trial_pool_id(grant),
        cents=trial_pool_cents(grant),
        day=grant.claimed_at.astimezone(UTC).date().isoformat(),
    )
    SignalTrialGrant.objects.for_team(team_id, canonical=True).filter(
        id=grant_id, billing_reported_at__isnull=True
    ).update(billing_reported_at=timezone.now())


def _snapshot_funded_delivery(
    *, organization_id: UUID, day: date, team_id: int, paid_spend: Decimal, trial_spend: dict[UUID, Decimal]
) -> None:
    cents = round(paid_spend + sum(trial_spend.values()))
    if not cents:
        return
    with transaction.atomic():
        # Child environments share a grant. Reserve its pool before creating their deliveries.
        grants = {
            grant.id: grant
            for grant in SignalTrialGrant.objects.for_team(team_id)
            .select_for_update()
            .filter(id__in=trial_spend)
            .order_by("id")
        }
        delivery, created = SignalRatedUsage.objects.unscoped().get_or_create(
            team_id=team_id, day=day, defaults={"organization_id": organization_id, "cents": cents}
        )
        if not created:
            return
        allocations: list[FrozenGrantAllocation] = []
        subtotal = paid_spend
        prior_cents = round(subtotal)
        for grant_id in sorted(trial_spend):
            grant = grants[grant_id]
            subtotal += trial_spend[grant_id]
            covered_cents = round(subtotal) - prior_cents
            prior_cents += covered_cents
            if not covered_cents:
                continue
            pool_cents = trial_pool_cents(grant)
            nominal_cents = (
                min(covered_cents, max(0, pool_cents - grant.billing_pool_allocated_cents))
                if grant.organization_id == organization_id
                else 0
            )
            if nominal_cents:
                allocations.append(
                    {
                        "grant_id": trial_pool_id(grant),
                        "cents": nominal_cents,
                        "pool_cents": pool_cents,
                        "pool_day": grant.claimed_at.astimezone(UTC).date().isoformat(),
                    }
                )
                grant.billing_pool_allocated_cents += nominal_cents
                grant.save(update_fields=["billing_pool_allocated_cents"])
            extra_cents = covered_cents - nominal_cents
            if extra_cents:
                # Accepted spillover, rounding and transferred grants remain PostHog-funded.
                allocations.append(
                    {
                        "grant_id": f"signals-trial-extra-{grant.id}-{delivery.id}",
                        "cents": extra_cents,
                        "pool_cents": extra_cents,
                        "pool_day": day.isoformat(),
                    }
                )
        delivery.grants = allocations
        delivery.save(update_fields=["grants"])


def snapshot_rated_usage(organization_id: UUID, day: date) -> None:
    begin = datetime.combine(day, time.min, UTC)
    totals = daily_spend(begin, begin + timedelta(days=1), organization_id=organization_id, include_running=False)
    paid_deliveries: list[SignalRatedUsage] = []
    for team_id, rows in groupby(totals, key=lambda row: row.team_id):
        paid_spend = Decimal(0)
        trial_spend: dict[UUID, Decimal] = {}
        for row in rows:
            if row.trial_grant_id is None:
                paid_spend = row.spend
            else:
                trial_spend[row.trial_grant_id] = row.spend
        if trial_spend:
            _snapshot_funded_delivery(
                organization_id=organization_id,
                day=day,
                team_id=team_id,
                paid_spend=paid_spend,
                trial_spend=trial_spend,
            )
        elif cents := round(paid_spend):
            paid_deliveries.append(
                SignalRatedUsage(team_id=team_id, organization_id=organization_id, day=day, cents=cents)
            )
    SignalRatedUsage.objects.unscoped().bulk_create(paid_deliveries, ignore_conflicts=True, batch_size=1000)
