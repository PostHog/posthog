"""Who a scanner's findings affected: counted from observations, exportable as a static cohort."""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType

DEFAULT_IMPACT_WINDOW_DAYS = 30

_IDENTIFIED = ~Q(distinct_id__isnull=True) & ~Q(distinct_id="")


@dataclass(frozen=True)
class ScannerImpact:
    affected_sessions: int
    identified_users: int
    unidentified_sessions: int
    window_days: int


def affected_observations(scanner: ReplayScanner, window_days: int) -> QuerySet[ReplayObservation]:
    """Succeeded observations that count as "affected"; for monitors only verdict-yes counts."""
    since = timezone.now() - timedelta(days=window_days)
    qs = ReplayObservation.objects.filter(
        scanner=scanner,
        team_id=scanner.team_id,
        status=ObservationStatus.SUCCEEDED,
        created_at__gte=since,
    )
    if scanner.scanner_type == ScannerType.MONITOR:
        qs = qs.filter(scanner_result__model_output__verdict="yes")
    return qs


def compute_scanner_impact(scanner: ReplayScanner, window_days: int = DEFAULT_IMPACT_WINDOW_DAYS) -> ScannerImpact:
    qs = affected_observations(scanner, window_days)
    return ScannerImpact(
        affected_sessions=qs.values("session_id").distinct().count(),
        identified_users=qs.filter(_IDENTIFIED).values("distinct_id").distinct().count(),
        unidentified_sessions=qs.exclude(_IDENTIFIED).values("session_id").distinct().count(),
        window_days=window_days,
    )


def create_affected_cohort(
    scanner: ReplayScanner, user: User | None, window_days: int = DEFAULT_IMPACT_WINDOW_DAYS
) -> tuple[Cohort, int]:
    """Static cohort of the identified users the scanner flagged; raises ValueError when the window has none."""
    distinct_ids = list(
        affected_observations(scanner, window_days).filter(_IDENTIFIED).values_list("distinct_id", flat=True).distinct()
    )
    if not distinct_ids:
        raise ValueError("No identified users in the window to save as a cohort.")

    cohort = Cohort.objects.create(
        team_id=scanner.team_id,
        name=f"Affected by {scanner.name} ({timezone.now().date().isoformat()})"[:400],
        description=f"Users flagged by the '{scanner.name}' scanner in the last {window_days} days. Static snapshot.",
        is_static=True,
        created_by=user,
    )
    try:
        cohort.insert_users_by_list(distinct_ids, team_id=scanner.team_id)
    except Exception:
        # Nothing references the cohort yet; don't leave an empty one behind.
        cohort.delete()
        raise
    return cohort, len(distinct_ids)
