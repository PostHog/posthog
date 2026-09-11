from datetime import timedelta
from typing import Any

from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobStatus
from products.endpoints.backend.logic.ducklake_shadow import run_ducklake_shadow_comparison
from products.endpoints.backend.logic.materialization import EndpointMaterializationService
from products.endpoints.backend.metrics import ENDPOINT_MATERIALIZATION_EVENT_TOTAL
from products.endpoints.backend.models import EndpointVersion
from products.endpoints.backend.notifications import notify_materialization_hibernated
from products.endpoints.backend.rate_limit import clear_endpoint_materialization_cache

logger = get_logger(__name__)

STALE_THRESHOLD_DAYS = 30


@shared_task(ignore_result=True, name="products.endpoints.backend.tasks.wake_hibernated_materialization")
def wake_hibernated_materialization(team_id: int, version_id: str, claimed_updated_at: str | None) -> None:
    try:
        version = (
            EndpointVersion.objects.filter(
                pk=version_id,
                endpoint__team_id=team_id,
                endpoint__deleted=False,
                endpoint__is_active=True,
                is_active=True,
                saved_query__isnull=True,
                materialization_hibernated_at__isnull=True,
                updated_at=claimed_updated_at,
            )
            .select_related("endpoint__team")
            .first()
        )
        if version is None or not version.can_materialize()[0]:
            return
        EndpointMaterializationService(version.endpoint.team).enable_materialization(
            version.endpoint,
            version,
            version.data_freshness_seconds,
            bucket_overrides=version.bucket_overrides,
        )
        ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="wake", status="success").inc()
    except Exception:
        logger.exception("wake_hibernated_materialization_failed", team_id=team_id, version_id=version_id)
        ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="wake", status="error").inc()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    name="products.endpoints.backend.tasks.shadow_compare_ducklake_execution",
)
@skip_team_scope_audit
def shadow_compare_ducklake_execution(
    team_id: int,
    endpoint_id: str,
    version_id: str,
    variables: dict[str, Any] | None,
    execution_type: str,
    clickhouse_cached: bool,
    clickhouse_ms: float,
    clickhouse_row_count: int | None,
    limit: int | None,
    offset: int | None,
) -> None:
    run_ducklake_shadow_comparison(
        team_id=team_id,
        endpoint_id=endpoint_id,
        version_id=version_id,
        variables=variables,
        execution_type=execution_type,
        clickhouse_cached=clickhouse_cached,
        clickhouse_ms=clickhouse_ms,
        clickhouse_row_count=clickhouse_row_count,
        limit=limit,
        offset=offset,
    )


@shared_task(ignore_result=True, name="products.endpoints.backend.tasks.deactivate_stale_materializations")
@skip_team_scope_audit
def deactivate_stale_materializations() -> None:
    """
    Hibernate materializations for endpoint versions unused for over 30 days.

    This task finds endpoint versions where:
    1. The version has an active materialization (saved_query.is_materialized = True)
    2. The materialization has run in the past 24h (a finished job, or saved_query.last_run_at)
    3. The materialization was enabled at least 30 days ago (saved_query.created_at)
    4. The version was last executed over 30 days ago (via API key), or was never called
       and is superseded or at least 30 days old

    For matching versions, the materialization is reverted to save resources.
    """
    now = timezone.now()
    twenty_four_hours_ago = now - timedelta(hours=24)
    stale_threshold = now - timedelta(days=STALE_THRESHOLD_DAYS)

    # A still-running job does not count: reverting soft-deletes the saved query under a live workflow.
    recent_job = DataModelingJob.objects.filter(
        saved_query_id=OuterRef("saved_query_id"),
        last_run_at__gte=twenty_four_hours_ago,
    ).exclude(status=DataModelingJobStatus.RUNNING)
    ran_recently = Q(saved_query__last_run_at__gte=twenty_four_hours_ago) | Q(Exists(recent_job))

    # Both stamps are written together on every API-key call, so a superseded version with no stamp
    # of its own has not been called since the stamp existed. The endpoint stamp belongs to the
    # version that replaced it.
    superseded = ~Q(version=F("endpoint__current_version"))
    never_called_and_old = Q(
        last_executed_at__isnull=True,
        endpoint__last_executed_at__isnull=True,
        created_at__lt=stale_threshold,
    )
    version_stale = (
        Q(last_executed_at__lt=stale_threshold)
        | Q(last_executed_at__isnull=True, endpoint__last_executed_at__lt=stale_threshold)
        | (Q(last_executed_at__isnull=True) & superseded)
        | never_called_and_old
    )

    stale_versions = EndpointVersion.objects.filter(
        ran_recently,
        version_stale,
        saved_query__isnull=False,
        saved_query__is_materialized=True,
        saved_query__deleted=False,
        saved_query__created_at__lte=stale_threshold,
        endpoint__deleted=False,
    ).select_related("saved_query", "endpoint")

    if not stale_versions.exists():
        logger.info("hibernate_stale_materializations_no_candidates")
        return

    deactivated_count = 0

    for version in stale_versions:
        try:
            _deactivate_version_materialization(version)
        except Exception as e:
            logger.exception(
                "hibernate_stale_materialization_failed",
                endpoint_id=str(version.endpoint.id),
                endpoint_name=version.endpoint.name,
                version=version.version,
                team_id=version.endpoint.team_id,
                error=str(e),
            )
            ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="hibernate", status="error").inc()
            continue
        deactivated_count += 1
        ENDPOINT_MATERIALIZATION_EVENT_TOTAL.labels(action="hibernate", status="success").inc()

    logger.info(
        "hibernate_stale_materializations_completed",
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
        "hibernating_stale_materialization",
        endpoint_id=str(version.endpoint.id),
        endpoint_name=version.endpoint.name,
        version=version.version,
        team_id=version.endpoint.team_id,
        last_executed_at=str(version.endpoint.last_executed_at) if version.endpoint.last_executed_at else None,
        last_run_at=str(saved_query.last_run_at) if saved_query.last_run_at else None,
    )

    version.disable_materialization(hibernating=True)
    clear_endpoint_materialization_cache(version.endpoint.team_id, version.endpoint.name, versions=[version.version])
    try:
        notify_materialization_hibernated(version)
    except Exception:
        logger.exception("notify_materialization_hibernated_failed", version_id=str(version.pk))
