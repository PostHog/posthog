from django.utils import timezone

import structlog
from celery import shared_task
from posthoganalytics import capture_exception

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import RECOMMENDATIONS_BY_TYPE

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, max_retries=0)
def compute_error_tracking_recommendation(recommendation_id: str) -> None:
    try:
        obj = ErrorTrackingRecommendation.objects.select_related("team").get(id=recommendation_id)
    except ErrorTrackingRecommendation.DoesNotExist:
        return

    rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
    if rec is None:
        ErrorTrackingRecommendation.objects.filter(id=obj.id).update(
            status=ErrorTrackingRecommendation.Status.READY,
            status_changed_at=timezone.now(),
        )
        return

    try:
        meta = rec.compute(obj.team)
    except Exception as e:
        capture_exception(e)
        logger.warning(
            "error_tracking_recommendation_compute_failed",
            team_id=obj.team_id,
            recommendation_type=obj.type,
            exc_info=True,
        )
        # Reset status so the next list() request can retry
        ErrorTrackingRecommendation.objects.filter(id=obj.id).update(
            status=ErrorTrackingRecommendation.Status.READY,
            status_changed_at=timezone.now(),
        )
        return

    now = timezone.now()
    ErrorTrackingRecommendation.objects.filter(id=obj.id).update(
        meta=meta,
        computed_at=now,
        status=ErrorTrackingRecommendation.Status.READY,
        status_changed_at=now,
    )
