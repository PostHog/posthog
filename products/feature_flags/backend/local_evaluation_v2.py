"""
Flag definitions v2 feed for SDK local evaluation.

The legacy feed (``local_evaluation.py``) leaves out every flag stored as a config version 2
document. This module builds a second body for the teams that hold such a flag: the legacy
response as it is, plus one entry per valid config version 2 flag.

The body has its own HyperCache entry and ETag. A team that holds no config version 2 flag
has no entry, because its legacy entry already is its complete feed. Nothing here writes,
reads or rebuilds the legacy entry.

The entry lives in Redis only. A reader decides from Redis alone whether a team has one, and
an object-storage copy would outlive every expiry.
"""

import json
import time
from collections import defaultdict
from typing import Any

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Q, QuerySet

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from posthoganalytics import capture_exception

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.dataclasses import frozen
from posthog.models.group_type_mapping import GroupTypesUnavailable
from posthog.models.team import Team
from posthog.redis import get_client
from posthog.storage.hypercache import HyperCache, HyperCacheDependencyUnavailable, KeyType, emit_cache_sync_metrics
from posthog.storage.hypercache_manager import HyperCacheManagementConfig

from products.experiments.backend.facade.feature_flags import flag_ids_with_live_experiment
from products.feature_flags.backend.facade.config import v2_config_lookup
from products.feature_flags.backend.flags_cache import _validates_v2, get_team_ids_with_recently_updated_flags
from products.feature_flags.backend.local_evaluation import (
    _FLAG_DEFINITIONS_REFRESH_ONLY_FIELDS,
    DATABASE_FOR_LOCAL_EVALUATION,
    _get_flags_response_for_local_evaluation_batch,
    _resolve_team,
    _skip_write_if_group_mapping_emptied,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag, serialize_feature_flags
from products.surveys.backend.models import Survey

logger = structlog.get_logger(__name__)

FLAG_DEFINITIONS_V2_CACHE_VALUE = "flags_with_cohorts_v2.json"
FLAG_DEFINITIONS_V2_CACHE_EXPIRY_SORTED_SET = "flag_definitions_v2_cache_expiry"
FLAG_DEFINITIONS_V2_CACHE_TYPE = "flag_definitions_v2"


@frozen
class _DefinitionsV2Batch:
    bodies: dict[int, dict[str, Any]]
    # Teams that hold a v2 flag and have no body, because their legacy response did not build.
    failed_team_ids: frozenset[int]
    # Teams whose v2 flags are all deleted.
    former_holder_team_ids: frozenset[int]


def _build_flag_definitions_v2_batch(teams: list[Team]) -> _DefinitionsV2Batch:
    """Build the v2 body of every team in ``teams`` that holds a config version 2 flag.

    One query finds those teams. A batch without one runs no other query. A v2 row never
    reaches the legacy builder's cohort or dependency transforms: the legacy builder
    excludes it, and its entry here is the stored document as it is.
    """
    rows = list(
        FeatureFlag.objects_including_soft_deleted.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(team_id__in=[team.id for team in teams], **v2_config_lookup())
        .annotate(
            evaluation_tag_names_agg=ArrayAgg(
                "flag_evaluation_contexts__evaluation_context__name",
                filter=Q(flag_evaluation_contexts__isnull=False),
                distinct=True,
            ),
        )
        .order_by("team_id", "key")
    )
    live_rows = [flag for flag in rows if not flag.deleted]
    holder_ids = {flag.team_id for flag in live_rows}
    former_holders = frozenset(flag.team_id for flag in rows if flag.team_id not in holder_ids)
    if not live_rows:
        return _DefinitionsV2Batch(bodies={}, failed_team_ids=frozenset(), former_holder_team_ids=former_holders)

    legacy_responses = _get_flags_response_for_local_evaluation_batch([team for team in teams if team.id in holder_ids])

    survey_flag_ids: set[int] = set()
    for survey_flags in (
        Survey.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(team_id__in=holder_ids)
        .values_list("targeting_flag_id", "internal_targeting_flag_id", "internal_response_sampling_flag_id")
    ):
        survey_flag_ids.update(flag_id for flag_id in survey_flags if flag_id is not None)
    live_experiment_flag_ids = flag_ids_with_live_experiment(
        [flag.pk for flag in live_rows], using=DATABASE_FOR_LOCAL_EVALUATION
    )

    carried: dict[int, list[FeatureFlag]] = defaultdict(list)
    for flag in live_rows:
        if flag.has_encrypted_payloads or flag.pk in survey_flag_ids:
            continue
        if not _validates_v2(flag.filters):
            logger.warning("Invalid v2 feature flag omitted from definitions", team_id=flag.team_id, flag_id=flag.pk)
            continue
        flag._evaluation_tag_names = flag.evaluation_tag_names_agg or []
        flag._has_experiment = flag.pk in live_experiment_flag_ids
        carried[flag.team_id].append(flag)

    return _DefinitionsV2Batch(
        bodies={
            team_id: {**legacy, "flags": [*legacy["flags"], *serialize_feature_flags(carried[team_id])]}
            for team_id, legacy in legacy_responses.items()
        },
        failed_team_ids=frozenset(holder_ids - legacy_responses.keys()),
        former_holder_team_ids=former_holders,
    )


def _refuse_cold_load(key: KeyType) -> dict[str, Any]:
    # A miss is an answer for this entry. Raising returns it as a miss and caches no sentinel.
    raise HyperCacheDependencyUnavailable("The flag definitions v2 entry is written by rebuilds, not loaded on read")


def _build_flag_definitions_v2_hypercache() -> HyperCache:
    has_dedicated_cache = FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES
    return HyperCache(
        namespace="feature_flags",
        value=FLAG_DEFINITIONS_V2_CACHE_VALUE,
        load_fn=_refuse_cold_load,
        cache_ttl=settings.FLAGS_CACHE_TTL,
        cache_miss_ttl=settings.FLAGS_CACHE_MISS_TTL,
        batch_load_fn=lambda teams: _build_flag_definitions_v2_batch(teams).bodies,
        enable_etag=True,
        expiry_sorted_set_key=FLAG_DEFINITIONS_V2_CACHE_EXPIRY_SORTED_SET,
        # The same Redis tiers as the legacy entry, so a reader finds both on the cluster it reads.
        cache_alias=FLAGS_DEDICATED_CACHE_ALIAS if has_dedicated_cache else None,
        secondary_cache_alias="default" if has_dedicated_cache else None,
        s3_enabled=False,
    )


flag_definitions_v2_hypercache = _build_flag_definitions_v2_hypercache()


def _holds_entry(team: Team) -> bool:
    cache = flag_definitions_v2_hypercache
    keys = [cache.get_cache_key(team), cache.get_etag_key(team)]
    clients = (cache.cache_client, cache.secondary_cache_client)
    return any(client.get_many(keys) for client in clients if client is not None)


def _remove_entry(team: Team) -> None:
    cache = flag_definitions_v2_hypercache
    # Passing the score keeps the tracking member when a delete fails, so upkeep visits the team again.
    score = get_client(cache.redis_url).zscore(FLAG_DEFINITIONS_V2_CACHE_EXPIRY_SORTED_SET, str(team.id))
    cache.delete_cache_entry(team, strict_mirror=True, tracked_expiry_score=score)


def update_flag_definitions_v2_cache(
    team: Team | int, ttl: int | None = None, *, skip_if_unchanged: bool = False, entry_expected: bool = True
) -> bool:
    """Bring one team's v2 entry in line with the database: write it while the team holds a
    config version 2 flag, remove it otherwise. Returns False when the entry was left as it was.

    A failure is logged and counted, and never raises, so the caller's legacy rebuild is not
    affected. ``entry_expected=False`` is for a caller that visits every team: a team that
    never held a config version 2 flag then costs the one query and no Redis call.
    """
    resolved_team = _resolve_team(team)
    if resolved_team is None:
        return False

    cache = flag_definitions_v2_hypercache
    start_time = time.time()
    size: int | None = None
    try:
        batch = _build_flag_definitions_v2_batch([resolved_team])
        body = batch.bodies.get(resolved_team.id)
        if body is not None:
            if _skip_write_if_group_mapping_emptied(resolved_team, body):
                return False
            size = cache.set_cache_value(resolved_team, body, ttl=ttl, skip_if_unchanged=skip_if_unchanged)
        elif resolved_team.id in batch.failed_team_ids:
            raise RuntimeError(f"Flag definitions v2 build failed for team {resolved_team.id}")
        elif entry_expected or (resolved_team.id in batch.former_holder_team_ids and _holds_entry(resolved_team)):
            _remove_entry(resolved_team)
        else:
            return True
    except SoftTimeLimitExceeded:
        raise
    except GroupTypesUnavailable:
        # The legacy rebuild reports this outage. Keep the existing entry.
        logger.warning("Skipped flag definitions v2 rebuild: group types unavailable", team_id=resolved_team.id)
        return False
    except Exception as e:
        capture_exception(e)
        logger.exception("Failed to sync flag definitions v2 cache for team", team_id=resolved_team.id)
        emit_cache_sync_metrics("failure", cache.namespace, cache.value, duration=time.time() - start_time)
        return False
    emit_cache_sync_metrics("success", cache.namespace, cache.value, duration=time.time() - start_time, size=size)
    return True


def _get_teams_with_flag_definitions_v2_queryset() -> "QuerySet[Team]":
    """Teams that hold a config version 2 flag, and teams whose entry is still tracked."""
    cache = flag_definitions_v2_hypercache
    tracked = get_client(cache.redis_url).zrange(FLAG_DEFINITIONS_V2_CACHE_EXPIRY_SORTED_SET, 0, -1)
    holders = (
        FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(**v2_config_lookup())
        .values_list("team_id", flat=True)
        .distinct()
    )
    return Team.objects.filter(id__in={*holders, *(int(member) for member in tracked)})


FLAG_DEFINITIONS_V2_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=flag_definitions_v2_hypercache,
    update_fn=update_flag_definitions_v2_cache,
    cache_name=FLAG_DEFINITIONS_V2_CACHE_TYPE,
    get_teams_queryset_fn=_get_teams_with_flag_definitions_v2_queryset,
    get_team_ids_to_skip_fix_fn=get_team_ids_with_recently_updated_flags,
    should_skip_write=_skip_write_if_group_mapping_emptied,
    refresh_only_fields=_FLAG_DEFINITIONS_REFRESH_ONLY_FIELDS,
    refresh_ttl_min_fraction=0.7,
)


def verify_team_flag_definitions_v2(
    team: Team,
    db_batch_data: dict | None = None,
    cache_batch_data: dict | None = None,
    verbose: bool = False,
) -> dict:
    """Verify a team's v2 entry against the database.

    The expected body is compared through its ETag. A team that holds no config version 2
    flag matches when it has no entry, and a mismatch without ``db_data`` makes the verifier
    call the update function, which removes the entry.
    """
    cache = flag_definitions_v2_hypercache
    if cache_batch_data and team.id in cache_batch_data:
        cached_data, _, etag = cache_batch_data[team.id]
    else:
        cached_data, _, etag = cache.batch_get_from_cache([team])[team.id]
    if db_batch_data is None:
        db_batch_data = _build_flag_definitions_v2_batch([team]).bodies
    expected = db_batch_data.get(team.id)

    if expected is None:
        if cached_data is None and etag is None:
            return {"status": "match", "issue": "", "details": ""}
        return {"status": "mismatch", "issue": "STALE_ENTRY", "details": "Entry for a team that holds no v2 flag"}
    if cached_data is None:
        return {"status": "miss", "issue": "CACHE_MISS", "details": "No cache entry found", "db_data": expected}
    if etag != cache._compute_etag(json.dumps(expected, sort_keys=True)):
        return {"status": "mismatch", "issue": "DATA_MISMATCH", "details": "ETag differs", "db_data": expected}
    return {"status": "match", "issue": "", "details": ""}
