import json
from collections import Counter
from dataclasses import dataclass, replace
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

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"BillingPeriod start must be before end: start={self.start}, end={self.end}")


def _current_month_bounds(now: datetime) -> BillingPeriod:
    return BillingPeriod(start=start_of_month(now), end=next_month_start(now))


def _as_utc(value: datetime) -> datetime:
    """Treat a tz-naive billing timestamp as UTC so it can be compared against tz-aware now."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _current_period_bounds(organization: Organization | None, now: datetime) -> BillingPeriod:
    """The org's active billing period when synced and current, else the calendar month containing `now`."""
    billing_period = organization.current_billing_period if organization else None
    if billing_period:
        start = _as_utc(billing_period.start)
        end = _as_utc(billing_period.end)
        # Gate before constructing so a malformed synced period falls back to the calendar month
        if start <= now < end:
            return BillingPeriod(start=start, end=end)
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

    This is the displayed figure, deliberately read from observation rows rather than the receipt ledger:
    it is what the scanner list column and the `credits_this_month` sort both show, and receipts carry no
    `scanner_id` before that column existed. `compute_scanner_budgets` is the delete-proof figure the
    limit is enforced against.

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


@dataclass(frozen=True)
class ScannerBudget(QuotaState):
    """A scanner's own allowance, carrying what one more observation costs.

    `credits_used` is the full draw: settled receipts plus live reservations. `settled_credits` is
    only what has actually posted to the ledger. Defaults exist only to satisfy the dataclass
    field-order rule, as `QuotaSnapshot` does; every constructor passes both.
    """

    credits_per_observation: int = 0
    settled_credits: int = 0

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
        return replace(self, credits_used=self.settled_credits).blocked


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
    organization_id: UUID, scanner_ids: list[UUID], period: BillingPeriod | None = None
) -> dict[UUID, ScannerBudget]:
    """Per-scanner budgets for the org's current billing period, with an entry for every requested scanner.

    Settled credits come from the immutable receipt ledger, so deleting observations cannot refund a
    scanner's limit. In-flight observations and running prompt evaluations are reserved live from their
    frozen snapshot model, exactly as the org snapshot does, because a sweep tick admits many
    observations concurrently against one read. Receipts written before `scanner_id` existed were
    backfilled from their observation rows (0070); only receipts whose observation was deleted
    before the backfill remain unattributed.

    Uncapped scanners skip the aggregates entirely and report zero usage: gates read `blocked`,
    which is always False without a limit, and the spend UI only renders for capped scanners.

    Pass `period` to bill against a window the caller already resolved, so an org snapshot and the
    scanner budgets taken alongside it cannot straddle a period boundary.
    """
    # Deferred: breaks the quota -> prompt_evaluation -> temporal -> quota import cycle.
    from products.replay_vision.backend.prompt_evaluation import (  # noqa: PLC0415
        in_flight_evaluation_credits_by_scanner,
    )

    if not scanner_ids:
        return {}
    if period is None:
        period = current_period_bounds(organization_id)
    # Limits are read here, not passed in: a caller that forgot them would silently disable enforcement.
    # `all_origins`: a capped inline scanner must resolve its limit here, or its budget reads as uncapped.
    # nosemgrep: idor-lookup-without-team (org-level aggregation, the pk__in list is co-filtered by team__organization_id, so a scanner id outside this org matches nothing)
    scanner_rows = ReplayScanner.all_origins.filter(
        team__organization_id=organization_id, pk__in=scanner_ids
    ).values_list("id", "credit_limit", "model")
    configs = {scanner_id: (limit, model) for scanner_id, limit, model in scanner_rows}
    # Almost every scanner is uncapped, so the spend aggregates run only for the capped ones; the
    # rest report zero usage, and `blocked` is always False without a limit.
    capped_ids = [scanner_id for scanner_id in scanner_ids if (configs.get(scanner_id) or (None,))[0] is not None]
    in_flight: dict[UUID, int] = {}
    in_flight_evaluations: dict[UUID, int] = {}
    settled: dict[UUID, int] = {}
    if capped_ids:
        # Reservations are read BEFORE the receipt ledger: an observation settling between the two reads
        # is then counted by both (a transient over-count that fails toward capped), never by neither.
        in_flight = _scanner_in_flight_credits(organization_id, capped_ids, period)
        # Evaluations write receipts directly, never observation rows, so a running test would otherwise
        # drain the cap invisibly. Not period-filtered: a live run charges whichever period it settles in.
        in_flight_evaluations = in_flight_evaluation_credits_by_scanner(organization_id, capped_ids)
        settled = {
            row["scanner_id"]: row["total_credits"] or 0
            for row in ReplayObservationUsage.objects.filter(
                organization_id=organization_id,
                scanner_id__in=capped_ids,
                observation_created_at__gte=period.start,
                observation_created_at__lt=period.end,
            )
            .values("scanner_id")
            .annotate(total_credits=Coalesce(Sum("credits"), Value(0), output_field=IntegerField()))
        }
    result: dict[UUID, ScannerBudget] = {}
    for scanner_id in scanner_ids:
        config = configs.get(scanner_id)
        settled_credits = settled.get(scanner_id, 0)
        reserved = in_flight.get(scanner_id, 0) + in_flight_evaluations.get(scanner_id, 0)
        result[scanner_id] = ScannerBudget(
            credit_limit=config[0] if config else None,
            credits_used=settled_credits + reserved,
            period_start=period.start,
            period_end=period.end,
            # A scanner outside this org or deleted mid-read has no model; pricing "" would log a warning.
            credits_per_observation=observation_credits_for_model(config[1]) if config else 0,
            settled_credits=settled_credits,
        )
    return result


def compute_scanner_budget(scanner: ReplayScanner, period: BillingPeriod | None = None) -> ScannerBudget:
    """This scanner's own credit allowance and draw for the org's current billing period."""
    budgets = compute_scanner_budgets(scanner.team.organization_id, [scanner.id], period)
    return budgets[scanner.id]


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
    # Skipped candidates were quoted and then scanned by the live sweep first, so the backfill no longer
    # owes their credits. Leaving them in strands phantom commitment for the rest of the run.
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
    # The tighter of billing's limit and the override, so a config mistake can only reduce credits;
    # this is how an internal org on an unlimited plan still gets a spend ceiling.
    override = ORG_CREDIT_LIMIT_OVERRIDES.get(str(organization_id))
    if override is not None:
        credit_limit = override if credit_limit is None else min(credit_limit, override)
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
