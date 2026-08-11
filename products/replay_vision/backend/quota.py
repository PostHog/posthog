from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from django.db.models import IntegerField, Sum, Value
from django.db.models.functions import Coalesce

import structlog
from dateutil.relativedelta import relativedelta

from posthog.date_util import start_of_month
from posthog.models.organization import Organization
from posthog.settings.utils import get_from_env

from products.replay_vision.backend.billing import FREE_TIER_MONTHLY_CREDITS, observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import (
    IN_FLIGHT_STATUSES,
    ObservationStatus,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.replay_scanner_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    ReplayScannerBackfill,
)

logger = structlog.get_logger(__name__)

# Fallback monthly credit cap for orgs billing has never synced (self-hosted, sync gaps, malformed
# limits). Matches the free plan's allocation so an unsynced org is never better off than a synced
# free-tier org; self-hosted deployments raise it via the env var.
MONTHLY_CREDIT_QUOTA = get_from_env("REPLAY_VISION_MONTHLY_CREDIT_QUOTA", FREE_TIER_MONTHLY_CREDITS, type_cast=int)

# Billing's usage_key for this product; see ee/billing/quota_limiting.QuotaResource.REPLAY_VISION_CREDITS.
USAGE_KEY = "replay_vision_credits"


@dataclass(frozen=True)
class QuotaState:
    """What the caps are and what has been spent. All amounts are credits (1 credit = $0.01).

    Everything enforcement needs and nothing it doesn't: deciding whether an observation may start
    reads only the limit and the spend so far. Projections live in `SpendProjection`, which costs
    extra queries no enforcement path should pay for.
    """

    # None means billing synced the product with no spend limit set: uncapped.
    credit_limit: int | None
    credits_used: int
    period_start: datetime
    period_end: datetime
    # Display-only: the slice of `credit_limit` that never bills; see FREE_TIER_MONTHLY_CREDITS.
    free_monthly_credits: int = FREE_TIER_MONTHLY_CREDITS

    @property
    def remaining(self) -> int | None:
        if self.credit_limit is None:
            return None
        return max(0, self.credit_limit - self.credits_used)

    @property
    def exhausted(self) -> bool:
        return self.credit_limit is not None and self.credits_used >= self.credit_limit

    def would_exceed(self, credits: int) -> bool:
        """Whether starting an observation costing `credits` would push usage past the limit (uncapped never does)."""
        return self.credit_limit is not None and self.credits_used + credits > self.credit_limit

    def affordable_count(self, credits_each: int) -> int | None:
        """How many observations at `credits_each` the remaining quota covers; None when nothing binds.

        Free models cost nothing, so they are never quota-bound; callers dividing by the price themselves
        have to remember that, and one of them did not.
        """
        remaining = self.remaining
        if remaining is None or credits_each <= 0:
            return None
        return remaining // credits_each


@dataclass(frozen=True)
class SpendProjection:
    """What the org has committed for the rest of the period. Display only; nothing enforces on this."""

    # Credit-weighted sum of enabled scanners' persisted estimates; uncomputed estimates count 0. A monthly rate.
    scanners_monthly_credits: int
    # Committed-but-unspent credits of active backfills. A one-off charge, not a rate.
    backfills_committed_credits: int

    @property
    def total(self) -> int:
        return self.scanners_monthly_credits + self.backfills_committed_credits


@dataclass(frozen=True)
class QuotaSnapshot(QuotaState):
    """`QuotaState` plus the projection, for the surfaces that show spend rather than gate on it."""

    projected_monthly_credits: int = 0
    scanners_monthly_credits: int = 0
    backfills_committed_credits: int = 0


def next_month_start(now: datetime) -> datetime:
    """First moment (UTC) of the calendar month following the month containing `now`."""
    return start_of_month(now) + relativedelta(months=1)


@dataclass(frozen=True)
class BillingPeriod:
    """Half-open [start, end) window observations are counted against."""

    start: datetime
    end: datetime


def _current_month_bounds(now: datetime) -> BillingPeriod:
    return BillingPeriod(start=start_of_month(now), end=next_month_start(now))


def _as_utc(value: datetime) -> datetime:
    """Treat a tz-naive billing timestamp as UTC so it can be compared against tz-aware now."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _current_period_bounds(organization: Organization | None, now: datetime) -> BillingPeriod:
    """The org's active billing period when synced and current, else the calendar month containing `now`."""
    billing_period = organization.current_billing_period if organization else None
    if billing_period:
        synced = BillingPeriod(start=_as_utc(billing_period.start), end=_as_utc(billing_period.end))
        if synced.start <= now < synced.end:
            return synced
    return _current_month_bounds(now)


def current_period_bounds(organization_id: UUID) -> BillingPeriod:
    """The org's active billing period when synced and current, else the current calendar month."""
    organization = Organization.objects.filter(pk=organization_id).only("usage").first()
    return _current_period_bounds(organization, datetime.now(UTC))


@dataclass(frozen=True)
class ScannerSpend:
    credits: int
    observations: int


def credits_used_by_scanner(organization_id: UUID, scanner_ids: list[UUID]) -> dict[UUID, ScannerSpend]:
    """Credits and observation counts for each scanner's succeeded observations in the current billing period.

    Priced at current rates from each observation's frozen snapshot model. Receipts freeze prices
    at success time, so these totals can drift from the billed ledger after a mid-period price
    change. Scanners with no spend are omitted.
    """
    if not scanner_ids:
        return {}
    period = current_period_bounds(organization_id)
    pairs = Counter(
        ReplayObservation.objects.filter(
            scanner_id__in=scanner_ids,
            team__organization_id=organization_id,
            status=ObservationStatus.SUCCEEDED,
            created_at__gte=period.start,
            created_at__lt=period.end,
        ).values_list("scanner_id", "scanner_snapshot__model")
    )
    totals: dict[UUID, ScannerSpend] = {}
    for (scanner_id, model), count in pairs.items():
        prev = totals.get(scanner_id, ScannerSpend(0, 0))
        totals[scanner_id] = ScannerSpend(
            credits=prev.credits + observation_credits_for_model(model or "") * count,
            observations=prev.observations + count,
        )
    return totals


def _sum_enabled_scanner_estimated_credits(organization_id: UUID, exclude_scanner_id: UUID | None = None) -> int:
    """Projected monthly credit spend from the org's enabled scanners' cached estimates."""
    scanners = ReplayScanner.objects.filter(team__organization_id=organization_id, enabled=True)
    if exclude_scanner_id is not None:
        scanners = scanners.exclude(pk=exclude_scanner_id)
    # Credit weighting happens in Python: the per-model price table lives in code, and orgs have few scanners.
    rows = scanners.values_list("model", "estimated_monthly_observations")
    return sum(observation_credits_for_model(model) * (estimate or 0) for model, estimate in rows)


def _sum_active_backfill_remaining_credits(organization_id: UUID) -> int:
    """Committed-but-unspent credits of the org's active backfills, priced at each backfill's frozen rate.

    Projection only: enforcement stays the per-observation creation check, identical for live and
    backfill applies. A new backfill's confirm dialog therefore sees earlier backfills' commitments
    inside the projected spend.
    """
    rows = (
        ReplayScannerBackfill.objects.unscoped()
        .filter(team__organization_id=organization_id, status__in=ACTIVE_BACKFILL_STATUSES)
        .values_list("total_count", "dispatched_count", "skipped_count", "credits_per_observation")
    )
    # Skipped candidates were counted at creation but will never be dispatched, so they are not a
    # commitment; leaving them in strands phantom credits in the projection for the whole run.
    return sum(max(0, total - dispatched - skipped) * price for total, dispatched, skipped, price in rows)


def _billing_synced_limit(organization: Organization | None) -> tuple[bool, int | None]:
    """(synced, limit): whether billing has synced this product, and the credit limit it synced (None = uncapped)."""
    if organization is None or not organization.usage:
        return False, None
    usage = organization.usage.get(USAGE_KEY)
    # Billing syncs `{}` for products it doesn't know about; only a summary that carries a
    # `limit` key (even a null one) means billing actually manages this product.
    if not usage or "limit" not in usage:
        return False, None
    limit = usage.get("limit")
    if limit is None:
        return True, None
    if isinstance(limit, (int, float)) and not isinstance(limit, bool):
        return True, int(limit)
    # A malformed limit must fail toward the env cap, never toward uncapped.
    logger.warning("replay_vision.malformed_billing_limit", organization_id=str(organization.id), limit=repr(limit))
    return False, None


def spend_projection(organization_id: UUID, exclude_scanner_id: UUID | None = None) -> SpendProjection:
    """The org's rest-of-period commitments, priced.

    `exclude_scanner_id` drops one scanner's stored estimate, for the editor's "others plus this
    proposal" forecast. Callers never touch the underlying scanner or backfill rows.
    """
    return SpendProjection(
        scanners_monthly_credits=_sum_enabled_scanner_estimated_credits(organization_id, exclude_scanner_id),
        backfills_committed_credits=_sum_active_backfill_remaining_credits(organization_id),
    )


def quota_state(organization_id: UUID) -> QuotaState:
    # noqa comment below: prompt_evaluation pulls in the temporal package, whose activities import
    # this module — deferring breaks the quota -> prompt_evaluation -> temporal -> quota cycle.
    from products.replay_vision.backend.prompt_evaluation import in_flight_evaluation_credits  # noqa: PLC0415

    # Single `now` so the usage window and any caller comparisons are computed from one instant.
    now = datetime.now(UTC)
    organization = Organization.objects.filter(pk=organization_id).only("usage").first()
    # Billing is the source of truth once synced, falling back to the env cap and calendar months otherwise.
    period = _current_period_bounds(organization, now)
    # Permanently-spent (succeeded) from the immutable ledger; deletes can't refund it.
    consumed = ReplayObservationUsage.objects.filter(
        organization_id=organization_id,
        observation_created_at__gte=period.start,
        observation_created_at__lt=period.end,
    ).aggregate(total=Coalesce(Sum("credits"), Value(0), output_field=IntegerField()))["total"]
    # In-flight rows aren't in the ledger yet (receipt is written on success), so reserve their credits live,
    # priced from the frozen snapshot model exactly as the eventual receipt will be. One created just before
    # a period rollover settles into the next window, so it is briefly counted in neither; accepted.
    in_flight_models = Counter(
        ReplayObservation.objects.filter(
            team__organization_id=organization_id,
            status__in=IN_FLIGHT_STATUSES,
            created_at__gte=period.start,
            created_at__lt=period.end,
        ).values_list("scanner_snapshot__model", flat=True)
    )
    in_flight = sum(observation_credits_for_model(model or "") * count for model, count in in_flight_models.items())
    # Prompt tests have no observation rows. Their unsettled sessions are committed spend too.
    usage = consumed + in_flight + in_flight_evaluation_credits(organization_id)
    synced, credit_limit = _billing_synced_limit(organization)
    if not synced:
        credit_limit = MONTHLY_CREDIT_QUOTA
    return QuotaState(
        credit_limit=credit_limit,
        credits_used=usage,
        period_start=period.start,
        period_end=period.end,
    )


def compute_quota_snapshot(organization_id: UUID) -> QuotaSnapshot:
    """Enforcement state plus the projection.

    Prefer `quota_state` wherever only the caps matter: this pays for two aggregates no gate reads.
    """
    state = quota_state(organization_id)
    projection = spend_projection(organization_id)
    return QuotaSnapshot(
        credit_limit=state.credit_limit,
        credits_used=state.credits_used,
        period_start=state.period_start,
        period_end=state.period_end,
        free_monthly_credits=state.free_monthly_credits,
        projected_monthly_credits=projection.total,
        scanners_monthly_credits=projection.scanners_monthly_credits,
        backfills_committed_credits=projection.backfills_committed_credits,
    )
