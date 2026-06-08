from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from dateutil.relativedelta import relativedelta

from posthog.date_util import start_of_month

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_quota_grant import ReplayQuotaGrant

MONTHLY_OBSERVATION_QUOTA = 3000

# In-flight rows count against the quota so concurrent on-demand triggers can't all race past the gate before any complete.
_COUNTED_STATUSES = (ObservationStatus.SUCCEEDED, ObservationStatus.PENDING, ObservationStatus.RUNNING)


@dataclass(frozen=True)
class QuotaSnapshot:
    monthly_quota: int
    usage_this_month: int
    period_start: datetime
    period_end: datetime

    @property
    def remaining(self) -> int:
        return max(0, self.monthly_quota - self.usage_this_month)

    @property
    def exhausted(self) -> bool:
        return self.usage_this_month >= self.monthly_quota


def _current_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    period_start = start_of_month(now)
    return period_start, period_start + relativedelta(months=1)


def compute_quota_snapshot(organization_id: UUID) -> QuotaSnapshot:
    # Single `now` so the usage window, bonus expiry, and any caller comparisons are computed from one instant.
    now = datetime.now(UTC)
    period_start, period_end = _current_month_bounds(now)
    usage = ReplayObservation.objects.filter(
        team__organization_id=organization_id,
        status__in=_COUNTED_STATUSES,
        created_at__gte=period_start,
        created_at__lt=period_end,
    ).count()
    bonus = ReplayQuotaGrant.objects.filter(
        organization_id=organization_id,
        expires_at__gt=now,
    ).aggregate(total=Coalesce(Sum("amount"), Value(0)))["total"]
    return QuotaSnapshot(
        monthly_quota=MONTHLY_OBSERVATION_QUOTA + bonus,
        usage_this_month=usage,
        period_start=period_start,
        period_end=period_end,
    )
