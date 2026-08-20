from typing import Any

from django.conf import settings

from posthog.caching.usage_ingestion_redis_cache import USAGE_INGESTION_CACHE_ALIAS
from posthog.models.team.team import Team
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType
from posthog.storage.hypercache_manager import HyperCacheManagementConfig

TEAM_ORGANIZATION_CACHE_TTL = 60 * 60 * 24 * 7
TEAM_ORGANIZATION_CACHE_MISS_TTL = 60 * 5
TEAM_ORGANIZATION_EXPIRY_SORTED_SET = "usage_ingestion:team_organization:expiry"


def _load_team_organization(team_key: KeyType) -> dict[str, str | int] | HyperCacheStoreMissing:
    try:
        team = HyperCache.team_from_key(team_key)
    except Team.DoesNotExist:
        return HyperCacheStoreMissing()

    return {"team_id": team.id, "organization_id": str(team.organization_id)}


team_organization_hypercache = HyperCache(
    namespace="usage_ingestion",
    value="organization_id.json",
    token_based=False,
    load_fn=_load_team_organization,
    cache_ttl=TEAM_ORGANIZATION_CACHE_TTL,
    cache_miss_ttl=TEAM_ORGANIZATION_CACHE_MISS_TTL,
    cache_alias=USAGE_INGESTION_CACHE_ALIAS if USAGE_INGESTION_CACHE_ALIAS in settings.CACHES else None,
    expiry_sorted_set_key=TEAM_ORGANIZATION_EXPIRY_SORTED_SET,
    bucket=settings.USAGE_INGESTION_OBJECT_STORAGE_BUCKET or settings.OBJECT_STORAGE_BUCKET,
)


def update_team_organization_cache(team: Team | int, ttl: int | None = None) -> bool:
    if not settings.USAGE_INGESTION_REDIS_URL:
        return False
    return team_organization_hypercache.update_cache(team, ttl=ttl)


def clear_team_organization_cache(team: Team | int, kinds: list[str] | None = None) -> None:
    if not settings.USAGE_INGESTION_REDIS_URL:
        return
    team_organization_hypercache.clear_cache(team, kinds=kinds)


def verify_team_organization(
    team: Team,
    db_batch_data: dict[str, Any] | None = None,
    cache_batch_data: dict[int, tuple[dict | None, str, str | None]] | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    expected = _load_team_organization(team)
    if isinstance(expected, HyperCacheStoreMissing):
        return {"status": "match", "issue": "", "details": "team not found"}

    if cache_batch_data and team.id in cache_batch_data:
        cached, source, _ = cache_batch_data[team.id]
    else:
        cached, source = team_organization_hypercache.get_from_cache_with_source(team)

    if cached is None:
        return {"status": "miss", "issue": "CACHE_MISS", "details": "No cached mapping found", "db_data": expected}

    if cached == expected:
        return {"status": "match", "issue": "", "details": ""}

    result: dict[str, Any] = {
        "status": "mismatch",
        "issue": "DATA_MISMATCH",
        "details": f"Mapping differs from {source}",
        "db_data": expected,
    }
    if verbose:
        result["cached_data"] = cached
    return result


TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=team_organization_hypercache,
    update_fn=update_team_organization_cache,
    cache_name="team_organization",
    refresh_only_fields=["id", "organization_id", "updated_at"],
)
