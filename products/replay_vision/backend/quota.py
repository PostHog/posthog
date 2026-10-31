import json
import math
import functools
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

from django.db.models import Count, IntegerField, QuerySet, Sum, Value
from django.db.models.functions import Coalesce, TruncDay

import structlog
from dateutil.relativedelta import relativedelta

from posthog.dataclasses import frozen
from posthog.date_util import start_of_month
from posthog.models.organization import Organization
from posthog.settings.utils import get_from_env

from products.replay_vision.backend.billing import (
    ESTIMATE_MONTH_DAYS,
    FREE_TIER_MONTHLY_CREDITS,
    observation_credits_for_model,
)
from products.replay_vision.backend.models.replay_observation import IN_FLIGHT_STATUSES, ReplayObservation
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


def _parse_org_credit_limit_overrides(raw: str) -> dict[str, int]:
    """JSON org-id -> monthly credit cap; malformed config fails toward no override, never toward a crash.

    Keys are normalized through `UUID`, so an id written in uppercase or without hyphens still caps the
    org it names. Matching the raw string would leave the cap silently unapplied, which is the state
    this setting exists to prevent. A bad entry is dropped on its own rather than voiding the rest.
    """
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected an object, got {type(parsed).__name__}")
    except (ValueError, TypeError):
        logger.exception("replay_vision.malformed_org_credit_limit_overrides")
        return {}

    overrides: dict[str, int] = {}
    for org_id, limit in parsed.items():
        try:
            key = str(UUID(str(org_id)))
            # `int(True)` is 1, which would cap an org at a single credit. Billing's own limit parser
            # rejects bools for the same reason.
            if isinstance(limit, bool):
                raise ValueError(f"credit limit must be a number, got {limit!r}")
            # A negative cap would read as "already over", so the worst a typo can do is block the org.
            overrides[key] = max(0, int(limit))
        except (ValueError, TypeError):
            logger.exception("replay_vision.invalid_org_credit_limit_override", org_id=str(org_id))
    if overrides:
        logger.info("replay_vision.org_credit_limit_overrides_applied", org_ids=sorted(overrides))
    return overrides


# Per-org monthly credit caps applied on top of billing's limit (the tighter one wins). For internal
# orgs on unlimited plans, where billing correctly syncs no limit but dogfooding spend still needs a
# ceiling. Enforcement and every spend surface treat it exactly like a billing limit.
ORG_CREDIT_LIMIT_OVERRIDES: dict[str, int] = get_from_env(
    "REPLAY_VISION_ORG_CREDIT_LIMIT_OVERRIDES", {}, type_cast=_parse_org_credit_limit_overrides
)

# Billing's usage_key for this product; see ee/billing/quota_limiting.QuotaResource.REPLAY_VISION_CREDITS.
USAGE_KEY = "replay_vision_credits"


@dataclass(frozen=True)
class QuotaState:
    """What the caps are and what has been spent. All amounts are credits (1 credit = $0.01).

    Everything enforcement needs and nothing it doesn't: deciding whether an observation may start
    reads only the limit and the spend so far. Projections live in `SpendProjection`, which costs
    extra queries no enforcement path should pay for.
    """

    # None means no limit applies: an org billing synced with no spend limit, or a scanner with no cap set.
    credit_limit: int | None
    # `credits_settled + credits_reserved`; kept as a field because gates read only this one number.
    credits_used: int
    period_start: datetime
    period_end: datetime
    # Display-only: the slice of `credit_limit` that never bills; see FREE_TIER_MONTHLY_CREDITS.
    free_monthly_credits: int = FREE_TIER_MONTHLY_CREDITS
    # Posted to the receipt ledger; deletes cannot refund it.
    credits_settled: int = 0
    # Held by in-flight observations; released without a receipt on failure.
    credits_reserved: int = 0

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
    # The scanners' share of that rate that lands before the period ends: the one rest-of-period figure
    # the meters, the spend chart and billing's forecast all read.
    scanners_period_credits: int = 0
    # The monthly rate the free credits still cover after the other free-only scanners and backfills.
    # Only the editor's forecast asks for it, so it is None unless requested.
    free_only_monthly_credits_left: int | None = None

    @property
    def total(self) -> int:
        return self.scanners_monthly_credits + self.backfills_committed_credits


@dataclass(frozen=True)
class QuotaSnapshot(QuotaState):
    """`QuotaState` plus the projection, for the surfaces that show spend rather than gate on it."""

    projected_monthly_credits: int = 0
    scanners_monthly_credits: int = 0
    backfills_committed_credits: int = 0
    scanners_period_credits: int = 0


def next_month_start(now: datetime) -> datetime:
    """First moment (UTC) of the calendar month following the month containing `now`."""
    return start_of_month(now) + relativedelta(months=1)


@dataclass(frozen=True)
class BillingPeriod:
    """Half-open [start, end) window observations are counted against."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"BillingPeriod start must be before end: start={self.start}, end={self.end}")


def _current_month_bounds(now: datetime) -> BillingPeriod:
    return BillingPeriod(start=start_of_month(now), end=next_month_start(now))


def _as_utc(value: datetime) -> datetime:
    """Treat a tz-naive billing timestamp as UTC so it can be compared against tz-aware now."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _roll_period_forward(start: datetime, end: datetime, now: datetime) -> BillingPeriod:
    """Advance a stale synced period along its own cadence until it contains `now`."""
    month_diff = (end.year - start.year) * 12 + end.month - start.month
    # Billing may close a period a second before the next one starts, so an end up to a day short
    # of the calendar boundary is still a whole-month period; the shortfall is carried along.
    for whole_months in (month_diff, month_diff + 1):
        if whole_months <= 0:
            continue
        shortfall = start + relativedelta(months=whole_months) - end
        if not timedelta(0) <= shortfall < timedelta(days=1):
            continue
        # Anniversary plans keep their day of month, so roll by calendar months from the original
        # start: re-anchoring on a February-clamped end would drift a day-31 plan.
        steps = 0
        while start + relativedelta(months=whole_months * (steps + 1)) - shortfall <= now:
            steps += 1
        return BillingPeriod(
            start=start + relativedelta(months=whole_months * steps),
            end=start + relativedelta(months=whole_months * (steps + 1)) - shortfall,
        )
    length = end - start
    elapsed = (now - start) // length
    start = start + elapsed * length
    return BillingPeriod(start=start, end=start + length)


def _current_period_bounds(organization: Organization | None, now: datetime) -> BillingPeriod:
    """The org's synced billing period rolled forward to contain `now`; the calendar month when unsynced.

    A billing sync that lags past the period's end must not snap the window to calendar months, or an
    anniversary-plan org would see its spend counted against a period boundary billing never uses.
    """
    billing_period = organization.current_billing_period if organization else None
    if billing_period:
        start = _as_utc(billing_period.start)
        end = _as_utc(billing_period.end)
        # A malformed or not-yet-started period cannot be rolled, so it falls back to the calendar month.
        if start < end and start <= now:
            return _roll_period_forward(start, end, now)
    return _current_month_bounds(now)


def current_period_bounds(organization_id: UUID) -> BillingPeriod:
    """The org's active billing period when synced and current, else the current calendar month."""
    return org_credit_cap(organization_id).period


@dataclass(frozen=True)
class ScannerSpend:
    credits: int
    observations: int


def scanner_period_receipts(organization_id: UUID, period: BillingPeriod) -> QuerySet[ReplayObservationUsage]:
    """Receipts in a period by observation create time: the per-scanner window. Billing buckets by receipt write time instead."""
    return ReplayObservationUsage.objects.filter(
        organization_id=organization_id,
        observation_created_at__gte=period.start,
        observation_created_at__lt=period.end,
    )


def credits_used_by_scanner(organization_id: UUID, scanner_ids: list[UUID]) -> dict[UUID, ScannerSpend]:
    """Billed credits and observation counts for each scanner in the current billing period.

    Read from the receipt ledger, so the figure matches what billing charged and what the credit limit
    counts: deleting an observation does not lower it, and each observation keeps the price frozen when
    it succeeded. Scanners with no spend are omitted.
    """
    if not scanner_ids:
        return {}
    period = current_period_bounds(organization_id)
    rows = (
        scanner_period_receipts(organization_id, period)
        .filter(scanner_id__in=scanner_ids)
        .values("scanner_id")
        .annotate(total_credits=Coalesce(Sum("credits"), 0), total_observations=Count("id"))
        .values_list("scanner_id", "total_credits", "total_observations")
    )
    return {
        scanner_id: ScannerSpend(credits, observations)
        for scanner_id, credits, observations in rows
        if scanner_id is not None  # `scanner_id__in` already excludes nulls; this narrows the type
    }


@dataclass(frozen=True)
class ScannerBudget(QuotaState):
    """A scanner's own allowance, carrying what one more observation costs.

    `credits_used` is the full draw: settled receipts plus live reservations, split as
    `credits_settled` and `credits_reserved`. The default exists only to satisfy the dataclass
    field-order rule, as `QuotaSnapshot` does; every constructor passes it.
    """

    credits_per_observation: int = 0
    # True when the org's free credits bind a free-only scanner, rather than its own limit.
    free_credits_bound: bool = False
    # A free-only scanner's other ceiling is full of posted spend, though this one leaves less room.
    other_ceiling_settled_blocked: bool = False

    @property
    def blocked(self) -> bool:
        """Whether this scanner is out of budget: the one answer every caller uses.

        `exhausted` and `would_exceed` disagree for a scanner with less than one observation of
        headroom left, which is exactly the state a capped scanner ends a period in. Gates and the
        API both read this so they cannot report different things about the same scanner.
        """
        return self.would_exceed(self.credits_per_observation)

    @property
    def blocked_by_settled_spend(self) -> bool:
        """`blocked` counting only credits that have posted.

        A reservation can release without ever writing a receipt (a failed observation), so an
        irreversible reaction to a cap must not fire on a transient in-flight spike.
        """
        return self.other_ceiling_settled_blocked or replace(self, credits_used=self.credits_settled).blocked

    @property
    def settled_block_from_free_credits(self) -> bool:
        """Whether the org's free credits, rather than the scanner's own limit, are the ceiling posted spend fills."""
        if replace(self, credits_used=self.credits_settled).blocked:
            return self.free_credits_bound
        # The other ceiling of a free-only scanner is the own limit when this one is the free credits, and back.
        return self.other_ceiling_settled_blocked and not self.free_credits_bound


def _scanner_in_flight_credits(
    organization_id: UUID, scanner_ids: list[UUID], period: BillingPeriod
) -> dict[UUID, int]:
    """Credits reserved by each scanner's in-flight rows, priced from the frozen snapshot model."""
    pairs = Counter(
        ReplayObservation.objects.filter(
            team__organization_id=organization_id,
            scanner_id__in=scanner_ids,
            status__in=IN_FLIGHT_STATUSES,
            created_at__gte=period.start,
            created_at__lt=period.end,
        ).values_list("scanner_id", "scanner_snapshot__model")
    )
    totals: dict[UUID, int] = {}
    for (scanner_id, model), count in pairs.items():
        totals[scanner_id] = totals.get(scanner_id, 0) + observation_credits_for_model(model or "") * count
    return totals


def compute_scanner_budgets(
    organization_id: UUID,
    scanner_ids: list[UUID],
    period: BillingPeriod | None = None,
    *,
    include_free_credits: bool = True,
    org_state: QuotaState | None = None,
) -> dict[UUID, ScannerBudget]:
    """Per-scanner budgets for the org's current billing period, with an entry for every requested scanner.

    Settled credits come from the immutable receipt ledger, so deleting observations cannot refund a
    scanner's limit. In-flight observations are reserved live from their
    frozen snapshot model, exactly as the org snapshot does, because a sweep tick admits many
    observations concurrently against one read. Receipts written before `scanner_id` existed were
    backfilled from their observation rows (0070); only receipts whose observation was deleted
    before the backfill remain unattributed.

    Uncapped scanners skip the aggregates entirely and report zero usage: gates read `blocked`,
    which is always False without a limit, and the spend UI only renders for capped scanners.

    Pass `period` to bill against a window the caller already resolved, so an org snapshot and the
    scanner budgets taken alongside it cannot straddle a period boundary.
    """
    if not scanner_ids:
        return {}
    if period is None:
        period = current_period_bounds(organization_id)
    # Limits are read here, not passed in: a caller that forgot them would silently disable enforcement.
    # `all_origins`: a capped inline scanner must resolve its limit here, or its budget reads as uncapped.
    # nosemgrep: idor-lookup-without-team (org-level aggregation, the pk__in list is co-filtered by team__organization_id, so a scanner id outside this org matches nothing)
    scanner_rows = ReplayScanner.all_origins.filter(
        team__organization_id=organization_id, pk__in=scanner_ids
    ).values_list("id", "credit_limit", "model", "free_only")
    configs: dict[UUID, tuple[int | None, str]] = {}
    free_only_ids: set[UUID] = set()
    for scanner_id, limit, model, free_only in scanner_rows:
        configs[scanner_id] = (limit, model)
        if free_only:
            free_only_ids.add(scanner_id)
    # Almost every scanner is uncapped, so the spend aggregates run only for the capped ones; the
    # rest report zero usage, and `blocked` is always False without a limit.
    capped_ids = [scanner_id for scanner_id in scanner_ids if (configs.get(scanner_id) or (None,))[0] is not None]
    in_flight: dict[UUID, int] = {}
    settled: dict[UUID, int] = {}
    if capped_ids:
        # Reservations are read BEFORE the receipt ledger: an observation settling between the two reads
        # is then counted by both (a transient over-count that fails toward capped), never by neither.
        in_flight = _scanner_in_flight_credits(organization_id, capped_ids, period)
        settled = {
            # The scanner_id__in filter excludes rows without a scanner.
            cast(UUID, row["scanner_id"]): row["total_credits"] or 0
            for row in scanner_period_receipts(organization_id, period)
            .filter(scanner_id__in=capped_ids)
            .values("scanner_id")
            .annotate(total_credits=Coalesce(Sum("credits"), Value(0), output_field=IntegerField()))
        }
    result: dict[UUID, ScannerBudget] = {}
    for scanner_id in scanner_ids:
        config = configs.get(scanner_id)
        settled_credits = settled.get(scanner_id, 0)
        reserved = in_flight.get(scanner_id, 0)
        result[scanner_id] = ScannerBudget(
            credit_limit=config[0] if config else None,
            credits_used=settled_credits + reserved,
            period_start=period.start,
            period_end=period.end,
            # A scanner outside this org or deleted mid-read has no model; pricing "" would log a warning.
            credits_per_observation=observation_credits_for_model(config[1]) if config else 0,
            credits_settled=settled_credits,
            credits_reserved=reserved,
        )
    if free_only_ids and include_free_credits:
        # A caller that already read the org's spend passes it, so the ledger is not read twice.
        free_budget = (
            _free_credits_budget_from_state(org_state)
            if org_state is not None
            else _free_credits_budget(organization_id, period)
        )
        for scanner_id in free_only_ids:
            own = result[scanner_id]
            free = replace(free_budget, credits_per_observation=own.credits_per_observation)
            # A free-only scanner can carry its own cap too; whichever leaves less room binds.
            tighter, other = sorted((own, free), key=lambda b: b.remaining if b.remaining is not None else math.inf)
            # The sweep's settled-only check still has to see a ceiling that posted spend already fills.
            result[scanner_id] = replace(tighter, other_ceiling_settled_blocked=other.blocked_by_settled_spend)
    return result


def compute_scanner_budget(
    scanner: ReplayScanner,
    period: BillingPeriod | None = None,
    *,
    include_free_credits: bool = True,
    org_state: QuotaState | None = None,
) -> ScannerBudget:
    """This scanner's own credit allowance and draw for the org's current billing period."""
    budgets = compute_scanner_budgets(
        scanner.team.organization_id,
        [scanner.id],
        period,
        include_free_credits=include_free_credits,
        org_state=org_state,
    )
    return budgets[scanner.id]


def _remaining_as_monthly_rate(budget: ScannerBudget | None, now: datetime) -> float:
    """The 30-day rate whose share of the days left lands exactly on what the budget has left."""
    if budget is None or budget.remaining is None:
        return math.inf
    days_left = max((budget.period_end - now).total_seconds() / 86400, 0)
    return budget.remaining * ESTIMATE_MONTH_DAYS / days_left if days_left > 0 else math.inf


@frozen
class ScannerRates:
    total: int
    # The share of `total` that free-only scanners draw from the org's free credits.
    free_only: int


def _sum_enabled_scanner_estimated_credits(
    organization_id: UUID,
    free_budget: Callable[[], ScannerBudget],
    exclude_scanner_id: UUID | None = None,
    free_credits_claimed: int = 0,
) -> ScannerRates:
    """Projected monthly credit spend of the org's enabled scanners' cached estimates.

    A capped scanner can only spend what its limit has left this period. Surfaces pro-rate this
    30-day rate over the days left, so that headroom is folded back into a rate: the pro-rated
    share then lands on exactly the remaining cap, never past it. Free-only scanners share one
    pool, the org's free credits left, so their rates are capped together rather than each in full.
    """
    scanners = ReplayScanner.objects.filter(team__organization_id=organization_id, enabled=True)
    if exclude_scanner_id is not None:
        scanners = scanners.exclude(pk=exclude_scanner_id)
    # Credit weighting happens in Python: the per-model price table lives in code, and orgs have few scanners.
    rows = list(scanners.values_list("id", "model", "estimated_monthly_observations", "credit_limit", "free_only"))
    capped_ids = [scanner_id for scanner_id, _, _, credit_limit, _ in rows if credit_limit is not None]
    has_free_only = any(free_only for *_, free_only in rows)
    period = current_period_bounds(organization_id) if capped_ids or has_free_only else None
    budgets = (
        compute_scanner_budgets(organization_id, capped_ids, period, include_free_credits=False) if capped_ids else {}
    )
    now = datetime.now(UTC)

    def capped_rate(rate: float, budget: ScannerBudget | None) -> float:
        return min(rate, _remaining_as_monthly_rate(budget, now))

    total = 0.0
    free_only_total = 0.0
    for scanner_id, model, estimate, _credit_limit, free_only in rows:
        rate = capped_rate(observation_credits_for_model(model) * (estimate or 0), budgets.get(scanner_id))
        if free_only:
            free_only_total += rate
        else:
            total += rate
    free_only_rate = 0.0
    if has_free_only and period is not None:
        # Free-only backfills already claim part of the pool, so the sweep rate gets only the rest.
        free = free_budget()
        free_only_rate = capped_rate(
            free_only_total, replace(free, credits_used=free.credits_used + free_credits_claimed)
        )
    return ScannerRates(total=round(total + free_only_rate), free_only=round(free_only_rate))


@frozen
class BackfillCommitments:
    paid: int
    # Committed by free-only scanners, which pause when the org's free credits run out.
    free_only: int


def _sum_active_backfill_remaining_credits(organization_id: UUID) -> BackfillCommitments:
    """Committed-but-unspent credits of the org's active backfills, priced at each backfill's frozen rate.

    Projection only: enforcement stays the per-observation creation check, identical for live and
    backfill applies. A new backfill's confirm dialog therefore sees earlier backfills' commitments
    inside the projected spend.
    """
    rows = (
        ReplayScannerBackfill.objects.unscoped()
        .filter(team__organization_id=organization_id, status__in=ACTIVE_BACKFILL_STATUSES)
        .values_list(
            "total_count", "dispatched_count", "skipped_count", "credits_per_observation", "scanner__free_only"
        )
    )
    # Skipped candidates were quoted and then scanned by the live sweep first, so the backfill no longer
    # owes their credits. Leaving them in strands phantom commitment for the rest of the run.
    committed = [
        (max(0, total - dispatched - skipped) * price, free_only)
        for total, dispatched, skipped, price, free_only in rows
    ]
    return BackfillCommitments(
        paid=sum(c for c, free_only in committed if not free_only),
        free_only=sum(c for c, free_only in committed if free_only),
    )


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
        if limit < 0:
            # A negative limit would read as permanently over; clamp to a hard block instead.
            logger.warning(
                "replay_vision.negative_billing_limit", organization_id=str(organization.id), limit=repr(limit)
            )
        return True, max(0, int(limit))
    # A malformed limit must fail toward the env cap, never toward uncapped.
    logger.warning("replay_vision.malformed_billing_limit", organization_id=str(organization.id), limit=repr(limit))
    return False, None


def _monthly_rate_to_period_credits(monthly_credits: float, period_end: datetime, now: datetime) -> int:
    """The part of a 30-day credit rate that lands between `now` and `period_end`."""
    days_left = max((period_end - now).total_seconds() / 86400, 0)
    return round(max(monthly_credits, 0) * days_left / ESTIMATE_MONTH_DAYS)


def spend_projection(
    organization_id: UUID,
    exclude_scanner_id: UUID | None = None,
    *,
    org_state: QuotaState | None = None,
    include_free_headroom: bool = False,
) -> SpendProjection:
    """The org's rest-of-period commitments, priced.

    `exclude_scanner_id` drops one scanner's stored estimate, for the editor's "others plus
    proposal" forecast. `org_state` is the org's spend when the caller already read it.
    `include_free_headroom` adds the free-credit rate left for one more free-only scanner. Callers
    never touch the underlying scanner or backfill rows.
    """

    @functools.cache
    def free_budget() -> ScannerBudget:
        state = org_state or quota_state(organization_id)
        return _free_credits_budget_from_state(state)

    backfills = _sum_active_backfill_remaining_credits(organization_id)
    free_only_backfills = backfills.free_only
    if free_only_backfills:
        # A free-only backfill pauses when the free credits run out, so it commits only what is left of them.
        credits_left = free_budget().remaining
        free_only_backfills = min(
            free_only_backfills, credits_left if credits_left is not None else free_only_backfills
        )
    rates = _sum_enabled_scanner_estimated_credits(
        organization_id, free_budget, exclude_scanner_id, free_credits_claimed=free_only_backfills
    )
    free_left: int | None = None
    if include_free_headroom:
        free = free_budget()
        pool = replace(free, credits_used=free.credits_used + free_only_backfills)
        pool_rate = _remaining_as_monthly_rate(pool, datetime.now(UTC))
        # Past the period end there is no rate to share, and an unbounded rate leaves nothing to cap.
        free_left = max(0, round(pool_rate - rates.free_only)) if math.isfinite(pool_rate) else 0
    period_end = org_state.period_end if org_state else current_period_bounds(organization_id).end
    return SpendProjection(
        scanners_monthly_credits=rates.total,
        backfills_committed_credits=backfills.paid + free_only_backfills,
        scanners_period_credits=_monthly_rate_to_period_credits(rates.total, period_end, datetime.now(UTC)),
        free_only_monthly_credits_left=free_left,
    )


@frozen
class UnreportedSpend:
    """An org's spend that a usage report has not counted yet, through to the period end."""

    # Credits, not a rate, so billing needs no clock.
    scanner_credits: int
    backfill_credits: int


def unreported_spend_by_org(report_cutoff: datetime) -> dict[UUID, UnreportedSpend]:
    """Every org's spend after a usage report's cutoff, for billing's forecast.

    The report counts receipts up to its cutoff, but the projection starts now. The spend in between,
    receipts since the cutoff and in-flight reservations, goes onto the scanner figure.
    """
    receipts = ReplayObservationUsage.objects.filter(created_at__gte=report_cutoff)
    # An org that switched its last scanner off after the cutoff still has that spend to report.
    org_ids = (
        set(ReplayScanner.objects.filter(enabled=True).values_list("team__organization_id", flat=True))
        | set(
            ReplayScannerBackfill.objects.unscoped()
            .filter(status__in=ACTIVE_BACKFILL_STATUSES)
            .values_list("team__organization_id", flat=True)
        )
        | set(
            ReplayObservation.objects.filter(status__in=IN_FLIGHT_STATUSES).values_list(
                "team__organization_id", flat=True
            )
        )
        | set(receipts.values_list("organization_id", flat=True).distinct())
    )
    # Reservations read BEFORE receipts: an observation settling between the two is counted twice, never zero times.
    states = {org_id: quota_state(org_id) for org_id in org_ids}
    receipts_since_cutoff = dict(
        receipts.filter(organization_id__in=org_ids)
        .values("organization_id")
        .annotate(total=Sum("credits"))
        .values_list("organization_id", "total")
    )
    result: dict[UUID, UnreportedSpend] = {}
    for org_id, state in states.items():
        projection = spend_projection(org_id, org_state=state)
        result[org_id] = UnreportedSpend(
            scanner_credits=projection.scanners_period_credits
            + (receipts_since_cutoff.get(org_id) or 0)
            + state.credits_reserved,
            backfill_credits=projection.backfills_committed_credits,
        )
    return result


@frozen
class OrgCreditCap:
    """The org's credit limit and the billing period it applies to, read without any spend aggregates."""

    period: BillingPeriod
    credit_limit: int | None


def _org_credit_limit(organization: Organization | None, organization_id: UUID) -> int | None:
    synced, credit_limit = _billing_synced_limit(organization)
    if not synced:
        credit_limit = MONTHLY_CREDIT_QUOTA
    # The tighter of billing's limit and the override, so a config mistake can only reduce credits;
    # this is how an internal org on an unlimited plan still gets a spend ceiling.
    override = ORG_CREDIT_LIMIT_OVERRIDES.get(str(organization_id))
    if override is not None:
        credit_limit = override if credit_limit is None else min(credit_limit, override)
    return credit_limit


def org_credit_cap(organization_id: UUID) -> OrgCreditCap:
    """One org read; billing is the source of truth once synced, else the env cap and calendar months."""
    organization = Organization.objects.filter(pk=organization_id).only("usage").first()
    return org_credit_cap_for(organization, organization_id)


def org_credit_cap_for(organization: Organization | None, organization_id: UUID) -> OrgCreditCap:
    """`org_credit_cap` for a caller that already loaded the org's `usage`."""
    return OrgCreditCap(
        period=_current_period_bounds(organization, datetime.now(UTC)),
        credit_limit=_org_credit_limit(organization, organization_id),
    )


def quota_state(organization_id: UUID) -> QuotaState:
    return quota_state_for_cap(organization_id, org_credit_cap(organization_id))


def quota_state_for_cap(organization_id: UUID, cap: OrgCreditCap) -> QuotaState:
    """The org's spend against a cap the caller already resolved, so the two cannot straddle a period boundary."""
    period = cap.period
    # In-flight rows aren't in the ledger yet (receipt is written on success), so reserve their credits live,
    # priced from the frozen snapshot model exactly as the eventual receipt will be. Every one counts toward
    # the current period, even one started before rollover, because that is where its receipt will land.
    # Read before the ledger: an observation settling between the two reads is then counted twice, which
    # fails toward capped, never in neither.
    in_flight_models = Counter(
        ReplayObservation.objects.filter(
            team__organization_id=organization_id,
            status__in=IN_FLIGHT_STATUSES,
        ).values_list("scanner_snapshot__model", flat=True)
    )
    # Permanently-spent (succeeded) from the immutable ledger; deletes can't refund it. Bucketed by receipt
    # write time, as billing buckets it, so the cap and the bill agree on which period a receipt belongs to.
    consumed = ReplayObservationUsage.objects.filter(
        organization_id=organization_id,
        created_at__gte=period.start,
        created_at__lt=period.end,
    ).aggregate(total=Coalesce(Sum("credits"), Value(0), output_field=IntegerField()))["total"]
    reserved = sum(observation_credits_for_model(model or "") * count for model, count in in_flight_models.items())
    return QuotaState(
        credit_limit=cap.credit_limit,
        credits_used=consumed + reserved,
        period_start=period.start,
        period_end=period.end,
        credits_settled=consumed,
        credits_reserved=reserved,
    )


def free_credits_ceiling(cap: OrgCreditCap) -> int:
    """The most a free-only scanner lets the org spend this period: the free credits, or less if billing caps lower."""
    if cap.credit_limit is None:
        return FREE_TIER_MONTHLY_CREDITS
    return min(cap.credit_limit, FREE_TIER_MONTHLY_CREDITS)


def _free_credits_budget(organization_id: UUID, period: BillingPeriod) -> ScannerBudget:
    cap = replace(org_credit_cap(organization_id), period=period)
    return _free_credits_budget_from_state(quota_state_for_cap(organization_id, cap))


def _free_credits_budget_from_state(state: QuotaState) -> ScannerBudget:
    return ScannerBudget(
        credit_limit=FREE_TIER_MONTHLY_CREDITS
        if state.credit_limit is None
        else min(state.credit_limit, FREE_TIER_MONTHLY_CREDITS),
        credits_used=state.credits_used,
        period_start=state.period_start,
        period_end=state.period_end,
        credits_settled=state.credits_settled,
        credits_reserved=state.credits_reserved,
        free_credits_bound=True,
    )


def compute_quota_snapshot(organization_id: UUID) -> QuotaSnapshot:
    """Enforcement state plus the projection.

    Prefer `quota_state` wherever only the caps matter: this pays for two aggregates no gate reads.
    """
    state = quota_state(organization_id)
    projection = spend_projection(organization_id, org_state=state)
    return QuotaSnapshot(
        credit_limit=state.credit_limit,
        credits_used=state.credits_used,
        period_start=state.period_start,
        period_end=state.period_end,
        free_monthly_credits=state.free_monthly_credits,
        credits_settled=state.credits_settled,
        credits_reserved=state.credits_reserved,
        projected_monthly_credits=projection.total,
        scanners_monthly_credits=projection.scanners_monthly_credits,
        backfills_committed_credits=projection.backfills_committed_credits,
        scanners_period_credits=projection.scanners_period_credits,
    )


@frozen
class DailySpend:
    date: date
    credits: int


@frozen
class DailySpendSeries:
    """Settled credits per UTC day from the period start through today, zero-filled and in order."""

    period_start: datetime
    period_end: datetime
    days: tuple[DailySpend, ...]


def daily_spend_series(organization_id: UUID) -> DailySpendSeries:
    now = datetime.now(UTC)
    organization = Organization.objects.filter(pk=organization_id).only("usage").first()
    # Same `now` as the window so the series can never straddle a period boundary.
    period = _current_period_bounds(organization, now)
    rows = (
        ReplayObservationUsage.objects.filter(
            organization_id=organization_id,
            created_at__gte=period.start,
            created_at__lt=period.end,
        )
        # Receipt write time, the same bucketing as the quota meter, so the days add up to its total.
        .annotate(day=TruncDay("created_at", tzinfo=UTC))
        .values("day")
        .annotate(total=Coalesce(Sum("credits"), Value(0), output_field=IntegerField()))
        .order_by()
        .values_list("day", "total")
    )
    credits_by_day = {day.date(): total for day, total in rows}
    first_day = period.start.date()
    day_count = (now.date() - first_day).days + 1
    days = tuple(
        DailySpend(date=day, credits=credits_by_day.get(day, 0))
        for day in (first_day + timedelta(days=offset) for offset in range(day_count))
    )
    return DailySpendSeries(period_start=period.start, period_end=period.end, days=days)
