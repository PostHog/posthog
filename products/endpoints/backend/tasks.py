from datetime import timedelta

from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from products.endpoints.backend.models import Endpoint

logger = get_logger(__name__)

STALE_THRESHOLD_DAYS = 30


@shared_task(ignore_result=True)
def deactivate_stale_materializations() -> None:
    """
    Deactivate materializations for endpoints that haven't been executed in over 30 days.

    This task finds endpoints where:
    1. The endpoint has an active materialization (saved_query.is_materialized = True)
    2. The materialization has run in the past 24h (saved_query.last_run_at within 24h)
    3. The materialization was enabled at least 30 days ago (saved_query.created_at)
    4. The endpoint was last executed over 30 days ago (via API key)

    For matching endpoints, the materialization is reverted to save resources.
    """
    now = timezone.now()
    twenty_four_hours_ago = now - timedelta(hours=24)
    stale_threshold = now - timedelta(days=STALE_THRESHOLD_DAYS)

    stale_endpoints = Endpoint.objects.filter(
        saved_query__isnull=False,
        saved_query__is_materialized=True,
        saved_query__last_run_at__gte=twenty_four_hours_ago,
        saved_query__deleted=False,
        saved_query__created_at__lte=stale_threshold,
        last_executed_at__lt=stale_threshold,
    ).select_related("saved_query")

    if not stale_endpoints.exists():
        logger.info("deactivate_stale_materializations_no_candidates")
        return

    deactivated_count = 0

    for endpoint in stale_endpoints:
        try:
            _deactivate_endpoint_materialization(endpoint)
            deactivated_count += 1
        except Exception as e:
            logger.exception(
                "deactivate_stale_materialization_failed",
                endpoint_id=str(endpoint.id),
                endpoint_name=endpoint.name,
                team_id=endpoint.team_id,
                error=str(e),
            )

    logger.info(
        "deactivate_stale_materializations_completed",
        deactivated_count=deactivated_count,
    )


def _deactivate_endpoint_materialization(endpoint: Endpoint) -> None:
    """
    Deactivate materialization for an endpoint.

    This reverts the materialization (removes Temporal schedule, cleans up S3 tables)
    and soft-deletes the saved_query.
    """
    saved_query = endpoint.saved_query
    if not saved_query:
        return

    logger.info(
        "deactivating_stale_materialization",
        endpoint_id=str(endpoint.id),
        endpoint_name=endpoint.name,
        team_id=endpoint.team_id,
        last_executed_at=str(endpoint.last_executed_at) if endpoint.last_executed_at else None,
        last_run_at=str(saved_query.last_run_at) if saved_query.last_run_at else None,
    )

    saved_query.revert_materialization()
    saved_query.soft_delete()
    endpoint.saved_query = None
    endpoint.save(update_fields=["saved_query"])
