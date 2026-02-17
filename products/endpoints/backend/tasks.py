from datetime import timedelta

from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from products.endpoints.backend.models import EndpointVersion

logger = get_logger(__name__)

STALE_THRESHOLD_DAYS = 30


@shared_task(ignore_result=True)
def deactivate_stale_materializations() -> None:
    """
    Deactivate materializations for endpoint versions that haven't been executed in over 30 days.

    This task finds endpoint versions where:
    1. The version has an active materialization (saved_query.is_materialized = True)
    2. The materialization has run in the past 24h (saved_query.last_run_at within 24h)
    3. The materialization was enabled at least 30 days ago (saved_query.created_at)
    4. The endpoint was last executed over 30 days ago (via API key)

    For matching versions, the materialization is reverted to save resources.
    """
    now = timezone.now()
    twenty_four_hours_ago = now - timedelta(hours=24)
    stale_threshold = now - timedelta(days=STALE_THRESHOLD_DAYS)

    stale_versions = EndpointVersion.objects.filter(
        saved_query__isnull=False,
        saved_query__is_materialized=True,
        saved_query__last_run_at__gte=twenty_four_hours_ago,
        saved_query__deleted=False,
        saved_query__created_at__lte=stale_threshold,
        endpoint__last_executed_at__lt=stale_threshold,
        endpoint__deleted=False,
    ).select_related("saved_query", "endpoint")

    if not stale_versions.exists():
        logger.info("deactivate_stale_materializations_no_candidates")
        return

    deactivated_count = 0

    for version in stale_versions:
        try:
            _deactivate_version_materialization(version)
            deactivated_count += 1
        except Exception as e:
            logger.exception(
                "deactivate_stale_materialization_failed",
                endpoint_id=str(version.endpoint.id),
                endpoint_name=version.endpoint.name,
                version=version.version,
                team_id=version.endpoint.team_id,
                error=str(e),
            )

    logger.info(
        "deactivate_stale_materializations_completed",
        deactivated_count=deactivated_count,
    )


def _deactivate_version_materialization(version: EndpointVersion) -> None:
    """
    Deactivate materialization for an endpoint version.

    This reverts the materialization (removes Temporal schedule, cleans up S3 tables)
    and soft-deletes the saved_query.
    """
    saved_query = version.saved_query
    if not saved_query:
        return

    logger.info(
        "deactivating_stale_materialization",
        endpoint_id=str(version.endpoint.id),
        endpoint_name=version.endpoint.name,
        version=version.version,
        team_id=version.endpoint.team_id,
        last_executed_at=str(version.endpoint.last_executed_at) if version.endpoint.last_executed_at else None,
        last_run_at=str(saved_query.last_run_at) if saved_query.last_run_at else None,
    )

    saved_query.revert_materialization()
    saved_query.soft_delete()
    version.saved_query = None
    version.is_materialized = False
    version.save(update_fields=["saved_query", "is_materialized"])
