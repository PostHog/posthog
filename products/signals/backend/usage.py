from collections.abc import Collection, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import Count, DateTimeField, F, Q, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, TruncDate
from django.db.models.lookups import GreaterThan, LessThanOrEqual

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalSpend
from products.signals.backend.trial.models import SignalTrialGrant


@frozen
class TrialUsage:
    settled_microusd: int
    running_microusd: int
    reports: int
    running_reports: int

    @property
    def spend_microusd(self) -> int:
        return self.settled_microusd + self.running_microusd

    def exhaustion_reason(self, grant: SignalTrialGrant) -> str:
        if self.spend_microusd >= grant.allowance_microusd:
            return "cost_limit"
        if self.reports + self.running_reports >= grant.report_limit:
            return "report_limit"
        return ""


def trial_usage(grant: SignalTrialGrant) -> TrialUsage:
    # The grant belongs to the canonical project, including its child environments.
    spend = (
        SignalSpend.objects.unscoped()
        .filter(trial_grant=grant)
        .aggregate(
            settled=Sum("spend", filter=Q(finalized_at__isnull=False), default=Decimal(0)),
            running=Sum("spend", filter=Q(finalized_at__isnull=True), default=Decimal(0)),
        )
    )
    delivered = Q(first_visible_at__gte=grant.claimed_at)
    running = Q(
        first_visible_at__isnull=True,
        self_driving_funding__grant_id=str(grant.id),
        status__in=[SignalReport.Status.POTENTIAL, SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS],
    )
    project_teams = Team.objects.filter(Q(id=grant.team_id) | Q(parent_team_id=grant.team_id)).values("id")
    reports = (
        SignalReport.objects.filter(team_id__in=project_teams)
        .filter(delivered | running)
        .filter(Q(billing_exempt_reason__isnull=True) | Q(billing_exempt_reason=""))
        .aggregate(
            delivered=Count("id", filter=delivered),
            running=Count("id", filter=running),
        )
    )
    return TrialUsage(
        settled_microusd=int(spend["settled"] * 10_000),
        running_microusd=int(spend["running"] * 10_000),
        reports=reports["delivered"],
        running_reports=reports["running"],
    )


@frozen
class DailySpend:
    team_id: int
    day: date
    trial_grant_id: UUID | None
    spend: Decimal


def daily_spend(
    begin: datetime,
    end: datetime,
    *,
    organization_id: str | UUID | None = None,
    organization_ids: Collection[str | UUID] | None = None,
    include_running: bool,
) -> Iterator[DailySpend]:
    if end <= begin:
        return
    # Trial receipts remain funded before Billing's cutover reaches the local usage JSON.
    eligible = Q(usage_billing=True, billing_exempt=False) | Q(trial_grant__isnull=False)
    if organization_id is not None:
        eligible &= Q(team__organization_id=organization_id)
    if organization_ids is not None:
        eligible &= Q(team__organization_id__in=organization_ids)
    # Running costs belong in quota checks before their final receipt becomes billable.
    now = datetime.now(UTC)
    period = Q(finalized_at__gte=begin, finalized_at__lt=end)
    if include_running and begin <= now < end:
        period_start = Cast(KeyTextTransform("0", "team__organization__usage__period"), DateTimeField())
        period_end = Cast(KeyTextTransform("1", "team__organization__usage__period"), DateTimeField())
        period |= Q(
            LessThanOrEqual(period_start, Value(now)),
            GreaterThan(period_end, Value(now)),
            finalized_at__isnull=True,
            created_at__gte=period_start,
        )
    usage_at = Coalesce("finalized_at", Value(now)) if include_running else F("finalized_at")
    # Deliberately cross-team: both usage reporting and organization quota use this aggregation.
    totals = (
        SignalSpend.objects.unscoped()
        .alias(usage_at=usage_at)
        .filter(eligible, period)
        .values("team_id", "trial_grant_id", day=TruncDate("usage_at", tzinfo=UTC))
        .annotate(total_spend=Sum("spend"))
        .order_by("team_id", "day", "trial_grant_id")
    )
    for total in totals.iterator(chunk_size=1000):
        yield DailySpend(
            team_id=total["team_id"],
            day=total["day"],
            trial_grant_id=total["trial_grant_id"],
            spend=total["total_spend"],
        )


def spend_credits_by_team(
    begin: datetime,
    end: datetime,
    *,
    organization_id: str | UUID | None = None,
    organization_ids: Collection[str | UUID] | None = None,
    include_running: bool,
) -> dict[int, int]:
    credits: dict[int, int] = {}
    # Round once per team/day, so a period recount equals the daily reports billing sums.
    for total in daily_spend(
        begin, end, organization_id=organization_id, organization_ids=organization_ids, include_running=include_running
    ):
        if total.trial_grant_id is None:
            credits[total.team_id] = credits.get(total.team_id, 0) + round(total.spend)
    return {team_id: amount for team_id, amount in credits.items() if amount}
