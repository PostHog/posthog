from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

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


@receiver(post_save, sender=Team)
def publish_team_organization_on_save(sender: type[Team], instance: Team, **kwargs: object) -> None:
    if not settings.USAGE_INGESTION_REDIS_URL:
        return

    transaction.on_commit(lambda: update_team_organization_cache_task.delay(instance.id))


@receiver(pre_delete, sender=Team)
def clear_team_organization_on_delete(sender: type[Team], instance: Team, **kwargs: object) -> None:
    clear_team_organization_cache(instance)


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
