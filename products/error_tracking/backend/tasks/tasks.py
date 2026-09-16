from django.utils import timezone

import structlog
from celery import shared_task
from posthoganalytics import capture_exception

from posthog.models.scoping import with_team_scope

from products.error_tracking.backend.logic.recommendations import RECOMMENDATIONS_BY_TYPE
from products.error_tracking.backend.models import ErrorTrackingRecommendation

logger = structlog.get_logger(__name__)


@shared_task(
    name="products.error_tracking.backend.tasks.compute_error_tracking_recommendation",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def compute_error_tracking_recommendation(recommendation_id: str, team_id: int) -> None:
    try:
        obj = ErrorTrackingRecommendation.objects.select_related("team").get(id=recommendation_id, team_id=team_id)
    except ErrorTrackingRecommendation.DoesNotExist:
        return

    rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
    if rec is None:
        ErrorTrackingRecommendation.objects.filter(id=obj.id, team_id=team_id).update(
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
        ErrorTrackingRecommendation.objects.filter(id=obj.id, team_id=team_id).update(
            status=ErrorTrackingRecommendation.Status.READY,
            status_changed_at=timezone.now(),
        )
        return

    now = timezone.now()
    ErrorTrackingRecommendation.objects.filter(id=obj.id, team_id=team_id).update(
        meta=meta,
        computed_at=now,
        status=ErrorTrackingRecommendation.Status.READY,
        status_changed_at=now,
    )


@shared_task(
    name="products.error_tracking.backend.tasks.dispatch_error_tracking_alert_deliveries",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
@with_team_scope()
def dispatch_error_tracking_alert_deliveries(team_id: int, notifications: list[dict]) -> None:
    """Start the delivery workflows for one transaction's worth of manual lifecycle transitions.

    Queued after commit so the request never waits on Temporal. Every start is
    idempotent on its notification id, so a retry after a partial failure only
    fills in the starts Temporal never accepted.
    """
    # Anything under the temporal package pulls in its aggregator, which loads every
    # worker-only workflow module (and, through recommendations, this tasks package):
    # keep it off this module's import path.
    from products.error_tracking.backend.temporal.alerts.dispatch import start_alert_delivery_workflows  # noqa: PLC0415
    from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs  # noqa: PLC0415

    start_alert_delivery_workflows([AlertDeliveryWorkflowInputs(**notification) for notification in notifications])
