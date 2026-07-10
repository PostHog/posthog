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

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import IN_FLIGHT_STATUSES, ReplayObservation
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_quota_grant import ReplayQuotaGrant
from products.replay_vision.backend.models.replay_scanner import ReplayScanner

logger = structlog.get_logger(__name__)

# Fallback monthly credit cap for orgs billing has never synced (self-hosted, pre-launch beta).
MONTHLY_CREDIT_QUOTA = get_from_env("REPLAY_VISION_MONTHLY_CREDIT_QUOTA", 15000, type_cast=int)

# Billing's usage_key for this product; see ee/billing/quota_limiting.QuotaResource.REPLAY_VISION_CREDITS.
USAGE_KEY = "replay_vision_credits"


@dataclass(frozen=True)
class QuotaSnapshot:
    """All amounts are credits (1 credit = $0.01)."""

    # None means billing synced the product with no spend limit set: uncapped.
    credit_limit: int | None
    credits_used: int
    period_start: datetime
    period_end: datetime
    # Credit-weighted sum of enabled scanners' persisted estimates across the org; uncomputed estimates count 0.
    projected_monthly_credits: int

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


def next_month_start(now: datetime) -> datetime:
    """First moment (UTC) of the calendar month following the month containing `now`."""
    return start_of_month(now) + relativedelta(months=1)


def _current_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    return start_of_month(now), next_month_start(now)


def _as_utc(value: datetime) -> datetime:
    """Treat a tz-naive billing timestamp as UTC so it can be compared against tz-aware now."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


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
    # Single `now` so the usage window, bonus expiry, and any caller comparisons are computed from one instant.
    now = datetime.now(UTC)
    organization = Organization.objects.filter(pk=organization_id).only("usage").first()
    # Billing is the source of truth once synced, falling back to the env cap and calendar months otherwise.
    billing_period = organization.current_billing_period if organization else None
    if billing_period:
        billing_period = (_as_utc(billing_period[0]), _as_utc(billing_period[1]))
    if billing_period and billing_period[0] <= now < billing_period[1]:
        period_start, period_end = billing_period
    else:
        period_start, period_end = _current_month_bounds(now)
    # Permanently-spent (succeeded) from the immutable ledger; deletes can't refund it.
    consumed = ReplayObservationUsage.objects.filter(
        organization_id=organization_id,
        observation_created_at__gte=period_start,
        observation_created_at__lt=period_end,
    ).aggregate(total=Coalesce(Sum("credits"), Value(0), output_field=IntegerField()))["total"]
    # In-flight rows aren't in the ledger yet (receipt is written on success), so reserve their credits live,
    # priced from the frozen snapshot model exactly as the eventual receipt will be.
    in_flight_models = Counter(
        ReplayObservation.objects.filter(
            team__organization_id=organization_id,
            status__in=IN_FLIGHT_STATUSES,
            created_at__gte=period_start,
            created_at__lt=period_end,
        ).values_list("scanner_snapshot__model", flat=True)
    )
    in_flight = sum(observation_credits_for_model(model or "") * count for model, count in in_flight_models.items())
    usage = consumed + in_flight
    bonus = ReplayQuotaGrant.objects.filter(
        organization_id=organization_id,
        expires_at__gt=now,
    ).aggregate(total=Coalesce(Sum("amount"), Value(0)))["total"]
    projected = sum_enabled_scanner_estimated_credits(organization_id)
    synced, base_limit = _billing_synced_limit(organization)
    if not synced:
        base_limit = MONTHLY_CREDIT_QUOTA
    # An uncapped synced org stays uncapped: bonuses only extend a real limit.
    credit_limit = base_limit + bonus if base_limit is not None else None
    return QuotaSnapshot(
        credit_limit=credit_limit,
        credits_used=usage,
        period_start=period_start,
        period_end=period_end,
        projected_monthly_credits=projected,
    )
