from datetime import datetime, timedelta

from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

import structlog
from posthoganalytics import capture_exception

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import RECOMMENDATIONS
from products.error_tracking.backend.recommendations.base import Recommendation
from products.error_tracking.backend.tasks import compute_error_tracking_recommendation

logger = structlog.get_logger(__name__)

# How long a recommendation can stay in "computing" before we consider the worker
# to have died and re-kick the computation.
COMPUTING_STUCK_AFTER = timedelta(minutes=5)


def is_stale(rec: Recommendation, obj: ErrorTrackingRecommendation, now: datetime) -> bool:
    if obj.computed_at is None:
        return True
    if rec.refresh_interval is None:
        return True
    return now >= obj.computed_at + rec.refresh_interval


def ensure_recommendation_row(rec: Recommendation, team_id: int) -> ErrorTrackingRecommendation:
    try:
        return ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)
    except ErrorTrackingRecommendation.DoesNotExist:
        try:
            return ErrorTrackingRecommendation.objects.create(
                team_id=team_id,
                type=rec.type,
                status=ErrorTrackingRecommendation.Status.READY,
            )
        except IntegrityError:
            return ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)


def claim_for_compute(obj_id, team_id: int, now: datetime) -> bool:
    """Atomically transition this recommendation into the 'computing' state.

    Returns True if we claimed the row (caller should run the computation), False if
    another worker already owns it and is still within the stuck threshold.
    """
    stuck_threshold = now - COMPUTING_STUCK_AFTER
    return (
        ErrorTrackingRecommendation.objects.filter(id=obj_id, team_id=team_id)
        .filter(
            Q(status=ErrorTrackingRecommendation.Status.READY)
            | Q(
                status=ErrorTrackingRecommendation.Status.COMPUTING,
                status_changed_at__lt=stuck_threshold,
            )
        )
        .update(
            status=ErrorTrackingRecommendation.Status.COMPUTING,
            status_changed_at=now,
        )
        == 1
    )


def revert_to_ready(obj_id, team_id: int) -> None:
    ErrorTrackingRecommendation.objects.filter(
        id=obj_id,
        team_id=team_id,
        status=ErrorTrackingRecommendation.Status.COMPUTING,
    ).update(
        status=ErrorTrackingRecommendation.Status.READY,
        status_changed_at=timezone.now(),
    )


def refresh_team_recommendations(team_id: int, *, compute_sync: bool) -> int:
    """Re-kick every stale recommendation for a team.

    Staleness is governed by each recommendation's ``refresh_interval``, so an hourly
    caller only recomputes the types that have actually gone stale (e.g. source_maps
    every 6h, long_running_issues every hour).

    ``compute_sync=True`` runs ``compute()`` inline — used by the Temporal background
    sweep so the work happens on the error-tracking worker. ``compute_sync=False``
    dispatches the existing Celery task — used by the on-demand API path.

    Returns the number of recommendations kicked.
    """
    now = timezone.now()
    kicked = 0
    for rec in RECOMMENDATIONS:
        try:
            obj = ensure_recommendation_row(rec, team_id)
            if not is_stale(rec, obj, now):
                continue
            if not claim_for_compute(obj.id, team_id, now):
                continue
            try:
                if compute_sync:
                    compute_error_tracking_recommendation(str(obj.id), team_id)
                else:
                    compute_error_tracking_recommendation.delay(str(obj.id), team_id)
                kicked += 1
            except Exception:
                revert_to_ready(obj.id, team_id)
                raise
        except Exception as e:
            capture_exception(e)
            logger.warning(
                "error_tracking_recommendation_kick_failed",
                team_id=team_id,
                recommendation_type=rec.type,
                exc_info=True,
            )
    return kicked
