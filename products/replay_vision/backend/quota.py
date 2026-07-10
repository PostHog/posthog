from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from dateutil.relativedelta import relativedelta

from posthog.date_util import start_of_month
from posthog.settings.utils import get_from_env

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_quota_grant import ReplayQuotaGrant
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.prompt_evaluation import in_flight_evaluation_sessions

MONTHLY_OBSERVATION_QUOTA = get_from_env("REPLAY_VISION_MONTHLY_OBSERVATION_QUOTA", 3000, type_cast=int)

# usage = ledger(succeeded) + live(in-flight); every quota-counting status must belong to exactly one source.
_IN_FLIGHT_STATUSES = (ObservationStatus.PENDING, ObservationStatus.RUNNING)


@dataclass(frozen=True)
class QuotaSnapshot:
    monthly_quota: int
    usage_this_month: int
    period_start: datetime
    period_end: datetime
    # Sum of enabled scanners' persisted per-scanner estimates across the org; uncomputed estimates count 0.
    projected_monthly_observations: int

    @property
    def remaining(self) -> int:
        return max(0, self.monthly_quota - self.usage_this_month)

    @property
    def exhausted(self) -> bool:
        return self.usage_this_month >= self.monthly_quota


def next_month_start(now: datetime) -> datetime:
    """First moment (UTC) of the calendar month following the month containing `now`."""
    return start_of_month(now) + relativedelta(months=1)


def _current_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    return start_of_month(now), next_month_start(now)


def sum_enabled_scanner_estimates(organization_id: UUID, exclude_scanner_id: UUID | None = None) -> int:
    """Projected monthly observation volume from the org's enabled scanners' cached estimates."""
    scanners = ReplayScanner.objects.filter(team__organization_id=organization_id, enabled=True)
    if exclude_scanner_id is not None:
        scanners = scanners.exclude(pk=exclude_scanner_id)
    return scanners.aggregate(total=Coalesce(Sum("estimated_monthly_observations"), Value(0)))["total"]


def compute_quota_snapshot(organization_id: UUID) -> QuotaSnapshot:
    # Single `now` so the usage window, bonus expiry, and any caller comparisons are computed from one instant.
    now = datetime.now(UTC)
    period_start, period_end = _current_month_bounds(now)
    # Permanently-spent (succeeded) from the immutable ledger; deletes can't refund it.
    consumed = ReplayObservationUsage.objects.filter(
        organization_id=organization_id,
        observation_created_at__gte=period_start,
        observation_created_at__lt=period_end,
    ).count()
    # In-flight rows aren't in the ledger yet (receipt is written on success), so add them live.
    in_flight = ReplayObservation.objects.filter(
        team__organization_id=organization_id,
        status__in=_IN_FLIGHT_STATUSES,
        created_at__gte=period_start,
        created_at__lt=period_end,
    ).count()
    # Prompt tests have no observation rows. Their unsettled sessions are committed spend too.
    usage = consumed + in_flight + in_flight_evaluation_sessions(organization_id)
    bonus = ReplayQuotaGrant.objects.filter(
        organization_id=organization_id,
        expires_at__gt=now,
    ).aggregate(total=Coalesce(Sum("amount"), Value(0)))["total"]
    projected = sum_enabled_scanner_estimates(organization_id)
    return QuotaSnapshot(
        monthly_quota=MONTHLY_OBSERVATION_QUOTA + bonus,
        usage_this_month=usage,
        period_start=period_start,
        period_end=period_end,
        projected_monthly_observations=projected,
    )
