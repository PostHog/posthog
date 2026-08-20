from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.team.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.cache_expiry_manager import cleanup_stale_expiry_tracking, refresh_expiring_caches
from posthog.tasks.utils import CeleryQueue

from ..team_organization_cache import (
    TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG,
    clear_team_organization_cache,
    update_team_organization_cache,
)

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def update_team_organization_cache_task(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        clear_team_organization_cache(team_id)
        return

    if not update_team_organization_cache(team):
        logger.warning("Failed to publish usage-ingestion team organization mapping", team_id=team_id)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_expiring_team_organization_cache_entries() -> None:
    if not settings.USAGE_INGESTION_REDIS_URL:
        return
    refresh_expiring_caches(TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours=24)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def cleanup_stale_team_organization_cache_entries() -> None:
    if not settings.USAGE_INGESTION_REDIS_URL:
        return
    cleanup_stale_expiry_tracking(TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG)
