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

logger = structlog.get_logger(__name__)

# Fallback monthly credit cap for orgs billing has never synced (self-hosted, sync gaps, malformed
# limits). Matches the free plan's allocation so an unsynced org is never better off than a synced
# free-tier org; self-hosted deployments raise it via the env var.
MONTHLY_CREDIT_QUOTA = get_from_env("REPLAY_VISION_MONTHLY_CREDIT_QUOTA", FREE_TIER_MONTHLY_CREDITS, type_cast=int)

# Billing's usage_key for this product; see ee/billing/quota_limiting.QuotaResource.REPLAY_VISION_CREDITS.
USAGE_KEY = "replay_vision_credits"


@dataclass(frozen=True)
class CreditBudget:
    """A credit allowance and what has been drawn against it. All amounts are credits (1 credit = $0.01)."""

    # None means no limit applies: an org billing synced with no spend limit, or a scanner with no cap set.
    credit_limit: int | None
    credits_used: int

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


@dataclass(frozen=True)
class QuotaSnapshot(CreditBudget):
    period_start: datetime
    period_end: datetime
    # Credit-weighted sum of enabled scanners' persisted estimates across the org; uncomputed estimates count 0.
    projected_monthly_credits: int
    # Display-only: the slice of `credit_limit` that never bills; see FREE_TIER_MONTHLY_CREDITS.
    free_monthly_credits: int = FREE_TIER_MONTHLY_CREDITS


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
class ScannerBudget(CreditBudget):
    """A scanner's own allowance, carrying what one more observation costs.

    `credits_used` is the full draw: settled receipts plus live reservations. `settled_credits` is
    only what has actually posted to the ledger.
    """

    credits_per_observation: int
    settled_credits: int

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
    observations concurrently against one read. Receipts written before `scanner_id` existed are null
    and count toward no scanner.

    Pass `period` to bill against a window the caller already resolved, so an org snapshot and the
    scanner budgets taken alongside it cannot straddle a period boundary.
    """
    # noqa comment below: prompt_evaluation pulls in the temporal package, whose activities import
    # this module. Deferring breaks the quota -> prompt_evaluation -> temporal -> quota cycle.
    from products.replay_vision.backend.prompt_evaluation import (  # noqa: PLC0415
        in_flight_evaluation_credits_by_scanner,
    )

    if not scanner_ids:
        return {}
    if period is None:
        period = current_period_bounds(organization_id)
    settled = {
        row["scanner_id"]: row["total_credits"] or 0
        for row in ReplayObservationUsage.objects.filter(
            organization_id=organization_id,
            scanner_id__in=scanner_ids,
            observation_created_at__gte=period.start,
            observation_created_at__lt=period.end,
        )
        .values("scanner_id")
        .annotate(total_credits=Coalesce(Sum("credits"), Value(0), output_field=IntegerField()))
    }
    in_flight = _scanner_in_flight_credits(organization_id, scanner_ids, period)
    # Evaluations write receipts directly and never create observation rows, so without this a running
    # test would drain a scanner's cap invisibly to every gate that reads this budget. Not period-filtered:
    # a run that is still alive will charge whichever period it settles in, as the org snapshot treats it.
    in_flight_evaluations = in_flight_evaluation_credits_by_scanner(organization_id, scanner_ids)
    # Read the limits here rather than taking them as a parameter: a caller that forgot to pass them
    # would get credit_limit=None, which reads as "uncapped" and would silently disable enforcement.
    # nosemgrep: idor-lookup-without-team (org-level aggregation, the pk__in list is co-filtered by team__organization_id, so a scanner id outside this org matches nothing)
    scanner_rows = ReplayScanner.objects.filter(team__organization_id=organization_id, pk__in=scanner_ids).values_list(
        "id", "credit_limit", "model"
    )
    configs = {scanner_id: (limit, model) for scanner_id, limit, model in scanner_rows}
    result: dict[UUID, ScannerBudget] = {}
    for scanner_id in scanner_ids:
        config = configs.get(scanner_id)
        settled_credits = settled.get(scanner_id, 0)
        reserved = in_flight.get(scanner_id, 0) + in_flight_evaluations.get(scanner_id, 0)
        result[scanner_id] = ScannerBudget(
            credit_limit=config[0] if config else None,
            credits_used=settled_credits + reserved,
            # An id outside this org, or a scanner deleted mid-read, has no model to price. Don't call
            # the price table with an empty string: it would log an unknown-model warning per call.
            credits_per_observation=observation_credits_for_model(config[1]) if config else 0,
            settled_credits=settled_credits,
        )
    return result


def compute_scanner_budget(scanner: ReplayScanner, period: BillingPeriod | None = None) -> ScannerBudget:
    """This scanner's own credit allowance and draw for the org's current billing period."""
    budgets = compute_scanner_budgets(scanner.team.organization_id, [scanner.id], period)
    return budgets[scanner.id]


def sum_enabled_scanner_estimated_credits(organization_id: UUID, exclude_scanner_id: UUID | None = None) -> int:
    """Projected monthly credit spend from the org's enabled scanners' cached estimates."""
    scanners = ReplayScanner.objects.filter(team__organization_id=organization_id, enabled=True)
    if exclude_scanner_id is not None:
        scanners = scanners.exclude(pk=exclude_scanner_id)
    # Credit weighting happens in Python: the per-model price table lives in code, and orgs have few scanners.
    rows = scanners.values_list("model", "estimated_monthly_observations")
    return sum(observation_credits_for_model(model) * (estimate or 0) for model, estimate in rows)


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


def compute_quota_snapshot(organization_id: UUID) -> QuotaSnapshot:
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
    projected = sum_enabled_scanner_estimated_credits(organization_id)
    synced, credit_limit = _billing_synced_limit(organization)
    if not synced:
        credit_limit = MONTHLY_CREDIT_QUOTA
    return QuotaSnapshot(
        credit_limit=credit_limit,
        credits_used=usage,
        period_start=period.start,
        period_end=period.end,
        projected_monthly_credits=projected,
    )
