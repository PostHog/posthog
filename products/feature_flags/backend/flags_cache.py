"""
Flags HyperCache for feature-flags service.

This module provides a HyperCache that stores feature flags for the feature-flags service.
Unlike the local_evaluation.py cache which provides rich data for SDKs (including cohorts
and group type mappings), this cache provides flag data plus the cohort definitions that
those flags actually reference.

The cache is automatically invalidated when:
- FeatureFlag models are created, updated, or deleted
- Team models are created or deleted (to ensure flag caches are cleaned up)
- EvaluationContext / FeatureFlagEvaluationContext models are created or deleted
- Cohort definitions are created, updated, or deleted (not recalculation-only saves)
- Hourly refresh job detects expiring entries (TTL < 24h)

Cache Key Pattern:
- Uses team_id as the key
- Stored in both Redis and S3 via HyperCache

Configuration:
- Redis TTL: 7 days (configurable via FLAGS_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via FLAGS_CACHE_MISS_TTL env var)

Manual operations:
    from products.feature_flags.backend.flags_cache import clear_flags_cache
    clear_flags_cache(team_id)
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.db.models import QuerySet

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_FLAGS_CACHE_INVALIDATION
from posthog.metrics import TOMBSTONE_COUNTER
from posthog.models.team import Team
from posthog.storage.cache_expiry_manager import (
    cleanup_stale_expiry_tracking as cleanup_generic,
    get_teams_with_expiring_caches,
    refresh_expiring_caches,
)
from posthog.storage.hypercache import HyperCache
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    get_cache_stats as get_cache_stats_generic,
)

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.dependencies import extract_cohort_dependencies
from products.experiments.backend.models.experiment import Experiment, live_experiment_exists
from products.feature_flags.backend.flags_cache_messages import FlagsCacheInvalidation
from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag, get_feature_flags, serialize_feature_flags

logger = structlog.get_logger(__name__)

# Sorted set key for tracking cache expirations
FLAGS_CACHE_EXPIRY_SORTED_SET = "flags_cache_expiry"


def _extract_direct_dependency_ids(flag_data: dict[str, Any]) -> set[int]:
    """
    Extract direct flag dependency IDs from a serialized flag's filters.

    Scans filters.groups[*].properties for type=="flag" properties and parses
    their key as an integer flag ID. Inactive/deleted flags return empty deps
    to match Rust's extract_dependencies behavior.
    """
    if not flag_data.get("active", True) or flag_data.get("deleted", False):
        return set()

    dep_ids: set[int] = set()
    filters = flag_data.get("filters", {})
    for group in filters.get("groups") or []:
        for prop in group.get("properties") or []:
            if prop.get("type") == "flag":
                try:
                    dep_ids.add(int(prop["key"]))
                except (ValueError, KeyError, TypeError):
                    continue
    return dep_ids


# Cohort model fields that change only during recalculation, not definition edits.
# Used by the post_save signal to avoid rebuilding the flags cache on every
# static cohort recalculation or count update.
# NOTE: cohort_type is included because calculate_people_ch() always saves it in
# update_fields even when unchanged. The rare actual cohort_type change (realtime
# exceeding person limit) uses Cohort.objects.filter().update() which bypasses signals.
_COHORT_RECALCULATION_FIELDS = frozenset(
    [
        "count",
        "version",
        "pending_version",
        "is_calculating",
        "last_calculation",
        "last_calculation_duration_ms",
        "errors_calculating",
        "last_error_at",
        # NOTE: `groups` is the legacy cohort-condition field (deprecated in favour of
        # `filters`).  calculate_people_ch() always saves it in update_fields even when
        # unchanged (see cohort.py:347).  Real definition changes go through a full save
        # (update_fields=None), so they still trigger invalidation.
        "groups",
        "cohort_type",
    ]
)


def _extract_cohort_ids_from_flag_filters(flags_data: list[dict[str, Any]]) -> set[int]:
    """Extract cohort IDs directly referenced in active flag filters.

    Only scans ``groups`` — the other filter sections cannot contain cohort
    properties:
    - ``feature_enrollment`` is a boolean gate for early-access features,
      evaluated against person properties (``$feature_enrollment/*``).
    - ``holdout`` uses a different schema for configuring experiment holdouts
      with no property filters at all.
    """
    cohort_ids: set[int] = set()
    for flag in flags_data:
        if not flag.get("active", True) or flag.get("deleted", False):
            continue
        for group in flag.get("filters", {}).get("groups") or []:
            for prop in group.get("properties") or []:
                if prop.get("type") == "cohort":
                    try:
                        cohort_ids.add(int(prop["value"]))
                    except (ValueError, KeyError, TypeError):
                        continue
    return cohort_ids


_MAX_COHORT_DEPENDENCY_DEPTH = 20


def _load_cohorts_with_deps(seed_ids: set[int], **team_filter: Any) -> dict[int, Cohort]:
    """BFS-load cohorts by seed IDs, resolving transitive cohort-on-cohort deps.

    Args:
        seed_ids: Initial cohort IDs to load.
        **team_filter: Passed to Cohort.objects.filter() for team scoping,
            e.g. team_id=5 or team_id__in={5, 6}.

    Returns:
        Dict mapping cohort PK to loaded Cohort instance.
    """
    if not seed_ids:
        return {}

    all_ids = set(seed_ids)
    ids_to_load = set(seed_ids)
    loaded: dict[int, Cohort] = {}
    depth = 0

    while ids_to_load:
        if depth >= _MAX_COHORT_DEPENDENCY_DEPTH:
            logger.warning(
                "Cohort dependency depth limit reached",
                depth=depth,
                remaining_ids=ids_to_load,
            )
            break
        depth += 1
        newly_loaded: list[Cohort] = []
        # nosemgrep: idor-lookup-without-team — team scope is enforced via **team_filter kwargs (team_id or team__project_id__in passed by caller).
        for cohort in Cohort.objects.filter(pk__in=ids_to_load, deleted=False, **team_filter):
            loaded[cohort.pk] = cohort
            newly_loaded.append(cohort)

        ids_to_load_next: set[int] = set()
        for cohort in newly_loaded:
            for dep_id in extract_cohort_dependencies(cohort):
                if dep_id not in all_ids:
                    all_ids.add(dep_id)
                    ids_to_load_next.add(dep_id)
        ids_to_load = ids_to_load_next

    return loaded


def _get_referenced_cohorts(team_id: int, flags_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch cohort definitions referenced by flags, including transitive cohort-on-cohort deps."""
    direct_ids = _extract_cohort_ids_from_flag_filters(flags_data)
    loaded = _load_cohorts_with_deps(direct_ids, team_id=team_id)
    return [_serialize_cohort(c) for c in loaded.values()]


def _serialize_cohort(cohort: Cohort) -> dict[str, Any]:
    """Serialize a Cohort to a dict matching the Rust Cohort struct field names.

    HYPERCACHE CONTRACT: These field names must match the Rust Cohort struct in
    rust/feature-flags/src/cohorts/cohort_models.rs. Field changes must follow
    the expand-and-contract pattern. The contract test will catch mismatches:
      pytest posthog/models/feature_flag/test/test_flags_cache.py -k "test_serializer_output_matches_fixture_schema"

    Note: deleted, is_calculating, is_static, errors_calculating, and groups
    are required by the Rust struct (no #[serde(default)]), so omitting them
    causes a deserialization failure.
    """
    return {
        "id": cohort.id,
        "name": cohort.name,
        "description": cohort.description,
        "team_id": cohort.team_id,
        "deleted": cohort.deleted,
        "filters": cohort.filters,
        "query": cohort.query,
        "version": cohort.version,
        "pending_version": cohort.pending_version,
        "count": cohort.count,
        "is_calculating": cohort.is_calculating,
        "is_static": cohort.is_static,
        "errors_calculating": cohort.errors_calculating,
        "groups": cohort.groups,
        "created_by_id": cohort.created_by_id,
        "cohort_type": cohort.cohort_type,
        "last_backfill_person_properties_at": (
            cohort.last_backfill_person_properties_at.isoformat() if cohort.last_backfill_person_properties_at else None
        ),
        "last_backfill_events_at": (
            cohort.last_backfill_events_at.isoformat() if cohort.last_backfill_events_at else None
        ),
    }


def _compute_flag_dependencies(flags_data: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute flag dependency metadata and return evaluation metadata.

    Returns a dict with:
    - dependency_stages: list of lists of flag IDs grouped by evaluation stage,
      stage 0 (no deps) first. Flags in the same stage can be evaluated in parallel.
    - flags_with_missing_deps: sorted list of flag IDs with missing, cyclic, or
      transitively broken dependencies.
    - transitive_deps: dict mapping stringified flag ID to sorted list of all
      transitive dependency flag IDs.

    Uses Kahn's algorithm (layered topological sort) to match the Rust fallback
    path's petgraph-based cycle handling: all cycle participants are excluded
    from stages, not just back-edge targets.
    """
    id_to_flag: dict[int, dict[str, Any]] = {}
    for flag in flags_data:
        flag_id = flag["id"]
        id_to_flag[flag_id] = flag

    # Build direct dependency edges (may reference unknown flag IDs)
    direct_deps: dict[int, set[int]] = {}
    for flag_id in id_to_flag:
        direct_deps[flag_id] = _extract_direct_dependency_ids(id_to_flag[flag_id])

    # Track flags with missing dependencies (dep ID not in id_to_flag)
    has_missing: dict[int, bool] = {
        fid: any(dep_id not in id_to_flag for dep_id in deps) for fid, deps in direct_deps.items()
    }

    # Build in-degree map (only count edges to known flags)
    in_degree: dict[int, int] = dict.fromkeys(id_to_flag, 0)
    # reverse_deps: flag_id → set of flags that depend on it
    reverse_deps: dict[int, set[int]] = {fid: set() for fid in id_to_flag}
    for flag_id, deps in direct_deps.items():
        for dep_id in deps:
            if dep_id in id_to_flag:
                in_degree[flag_id] += 1
                reverse_deps[dep_id].add(flag_id)

    # Kahn's algorithm: peel layers of zero-in-degree nodes
    dependency_stages: list[list[int]] = []
    transitive_deps: dict[int, set[int]] = {}
    queue = sorted(fid for fid, deg in in_degree.items() if deg == 0)

    while queue:
        for fid in queue:
            # Compute transitive deps: union of each dep's transitive closure + direct deps
            td: set[int] = set()
            for dep_id in direct_deps[fid]:
                if dep_id in id_to_flag:
                    td.add(dep_id)
                    td.update(transitive_deps[dep_id])
                    if has_missing[dep_id]:
                        has_missing[fid] = True
            transitive_deps[fid] = td

        dependency_stages.append(queue)

        next_queue: list[int] = []
        for fid in queue:
            for dependent_id in reverse_deps[fid]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    next_queue.append(dependent_id)
        queue = sorted(next_queue)

    # Flags still with in_degree > 0 are in cycles.
    cycled_flags = {fid for fid, deg in in_degree.items() if deg > 0}
    for fid in cycled_flags:
        has_missing[fid] = True

    return {
        "dependency_stages": dependency_stages,
        "flags_with_missing_deps": sorted(fid for fid, m in has_missing.items() if m),
        "transitive_deps": {str(fid): sorted(transitive_deps.get(fid, set())) for fid in id_to_flag},
    }


def _get_feature_flags_for_service(team: Team) -> dict[str, Any]:
    """
    Get feature flags for the feature-flags service.

    HYPERCACHE CONTRACT: The top-level keys (flags, evaluation_metadata, cohorts)
    must match rust/feature-flags/src/flags/flag_models.rs::HypercacheFlagsWrapper.
    Changes to this structure must follow the expand-and-contract pattern.

    Fetches all feature flags for the team (including inactive, excluding deleted)
    and returns them wrapped in a dict that HyperCache can serialize. The actual
    flag data is in the "flags" key as a list of flag dictionaries.

    Encrypted remote config flags are excluded since they can only be accessed via
    the dedicated /remote_config endpoint which handles decryption. Including them
    in /flags would return unusable encrypted ciphertext.

    Returns:
        dict: {"flags": [...], "evaluation_metadata": {...}, "cohorts": [...]} where
        flags is a list of flag dictionaries, evaluation_metadata contains pre-computed
        dependency metadata (stages, missing deps, transitive deps), and cohorts contains
        serialized cohort definitions referenced by the flags (including transitive deps).
    """
    flags = get_feature_flags(team=team, exclude_encrypted_payloads=True)
    flags_data = serialize_feature_flags(flags)
    evaluation_metadata = _compute_flag_dependencies(flags_data)

    cohorts = _get_referenced_cohorts(team.id, flags_data)

    logger.info(
        "Loaded feature flags for service cache",
        team_id=team.id,
        project_id=team.project_id,
        flag_count=len(flags_data),
        cohort_count=len(cohorts),
    )

    # Wrap in dict for HyperCache compatibility
    return {"flags": flags_data, "evaluation_metadata": evaluation_metadata, "cohorts": cohorts}


def _get_feature_flags_for_teams_batch(teams: list[Team]) -> dict[int, dict[str, Any]]:
    """
    Batch load feature flags for multiple teams in one query.

    This avoids N+1 queries by loading all flags for all teams at once,
    then grouping them by team_id.

    Encrypted remote config flags are excluded since they can only be accessed via
    the dedicated /remote_config endpoint which handles decryption. Including them
    in /flags would return unusable encrypted ciphertext.

    Args:
        teams: List of Team objects to load flags for

    Returns:
        Dict mapping team_id to {"flags": [...], "evaluation_metadata": {...}, "cohorts": [...]} for each team
    """
    if not teams:
        return {}

    # Load all flags for all teams in one query with evaluation tags pre-loaded.
    # Include disabled flags (active=False) so flag dependencies can reference them
    # and evaluate them as false, rather than raising DependencyNotFound errors.
    # Exclude encrypted payload flags - they can only be accessed via the
    # dedicated /remote_config endpoint which handles decryption.
    # Note: We intentionally don't select_related("team") here because we only need
    # team_id (already on the model) for grouping, and the Team objects are already
    # loaded by the caller. Avoiding the join saves memory.
    all_flags = list(
        FeatureFlag.objects.filter(team__in=teams)
        .exclude(has_encrypted_payloads=True)
        .annotate(
            evaluation_tag_names_agg=ArrayAgg(
                "flag_evaluation_contexts__evaluation_context__name",
                filter=Q(flag_evaluation_contexts__isnull=False),
                distinct=True,
            ),
            has_experiment_agg=live_experiment_exists(),
        )
    )

    # Transfer aggregated tag names to model instances
    for flag in all_flags:
        flag._evaluation_tag_names = flag.evaluation_tag_names_agg or []
        flag._has_experiment = flag.has_experiment_agg

    # Group flags by team_id
    flags_by_team_id: dict[int, list[FeatureFlag]] = defaultdict(list)
    for flag in all_flags:
        flags_by_team_id[flag.team_id].append(flag)

    # Serialize flags for each team and collect all referenced cohort IDs
    flags_data_by_team: dict[int, list[dict[str, Any]]] = {}
    all_cohort_ids: set[int] = set()
    for team in teams:
        team_flags = flags_by_team_id.get(team.id, [])
        flags_data = serialize_feature_flags(team_flags)
        flags_data_by_team[team.id] = flags_data
        all_cohort_ids.update(_extract_cohort_ids_from_flag_filters(flags_data))

    # Batch-load all referenced cohorts across all teams (including transitive deps)
    team_ids = {t.id for t in teams}
    loaded_cohorts = _load_cohorts_with_deps(all_cohort_ids, team_id__in=team_ids)

    # Group loaded cohorts by team_id
    cohorts_by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for cohort in loaded_cohorts.values():
        cohorts_by_team[cohort.team_id].append(_serialize_cohort(cohort))

    # Build result for each team
    result: dict[int, dict[str, Any]] = {}
    for team in teams:
        flags_data = flags_data_by_team[team.id]
        evaluation_metadata = _compute_flag_dependencies(flags_data)

        team_cohorts = cohorts_by_team.get(team.id, [])
        logger.info(
            "Loaded feature flags for service cache (batch)",
            team_id=team.id,
            project_id=team.project_id,
            flag_count=len(flags_data),
            cohort_count=len(team_cohorts),
        )

        result[team.id] = {
            "flags": flags_data,
            "evaluation_metadata": evaluation_metadata,
            "cohorts": team_cohorts,
        }

    return result


# HyperCache instance for feature-flags service
# Use dedicated flags cache alias if available, otherwise defaults to default cache
flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags.json",
    load_fn=lambda key: _get_feature_flags_for_service(HyperCache.team_from_key(key)),
    cache_ttl=settings.FLAGS_CACHE_TTL,
    cache_miss_ttl=settings.FLAGS_CACHE_MISS_TTL,
    cache_alias=FLAGS_DEDICATED_CACHE_ALIAS if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES else None,
    batch_load_fn=_get_feature_flags_for_teams_batch,
    expiry_sorted_set_key=FLAGS_CACHE_EXPIRY_SORTED_SET,
    # Etag is consumed by the Rust feature-flags service in-memory cache
    # (FlagDefinitionsCache), keyed on (team_id, etag). Without this, the cache
    # bypass branch fires on every request and the perf opt is wasted.
    enable_etag=True,
)


def get_flags_from_cache(team: Team) -> list[dict[str, Any]] | None:
    """
    Get feature flags from the cache for a team.

    Only operates when FLAGS_REDIS_URL is configured to avoid reading from/writing to shared cache.

    Args:
        team: The team to get flags for

    Returns:
        list: Flag dictionaries (empty list if team has zero flags)
        None: Cache miss or FLAGS_REDIS_URL not configured
    """
    if not settings.FLAGS_REDIS_URL:
        return None

    result = flags_hypercache.get_from_cache(team)
    if result is None:
        return None
    return result.get("flags", [])


def update_flags_cache(team: Team | int, ttl: int | None = None) -> bool:
    """
    Update the flags cache for a team.

    This explicitly updates both Redis and S3 with the latest flag data.
    Only operates when FLAGS_REDIS_URL is configured to avoid writing to shared cache.
    Expiry tracking is handled automatically by HyperCache.set_cache_value().

    Args:
        team: Team object or team ID
        ttl: Optional custom TTL in seconds (defaults to FLAGS_CACHE_TTL)

    Returns:
        True if cache update succeeded, False otherwise
    """
    if not settings.FLAGS_REDIS_URL:
        return False

    success = flags_hypercache.update_cache(team, ttl=ttl)

    if not success:
        team_id = team.id if isinstance(team, Team) else team
        logger.warning("Failed to update flags cache", team_id=team_id)

    return success


def verify_team_flags(
    team: Team,
    db_batch_data: dict | None = None,
    cache_batch_data: dict | None = None,
    verbose: bool = False,
) -> dict:
    """
    Verify a team's flags cache against the database.

    Args:
        team: Team to verify
        db_batch_data: Pre-loaded DB data from batch_load_fn (keyed by team.id)
        cache_batch_data: Pre-loaded cache data from batch_get_from_cache (keyed by team.id)
        verbose: If True, include detailed diffs with flag keys and field-level differences

    Returns:
        Dict with 'status' ("match", "miss", "mismatch") and 'issue' type.
        When verbose=True, includes 'diffs' list with detailed diff information.
    """
    # Get cached data - use pre-loaded batch data if available (single MGET for whole batch).
    # The etag rides on the same MGET when enable_etag=True, so the MISSING_ETAG check
    # below stays per-chunk and never re-introduces a per-team Redis GET.
    if cache_batch_data and team.id in cache_batch_data:
        cached_data, source, cached_etag = cache_batch_data[team.id]
    else:
        # Single-team fallback (CLI verifier path; the management command does
        # not pre-fetch cache_batch_data). Reuse the batch shape so payload +
        # etag come from one MGET and stay consistent under concurrent writes.
        batch = flags_hypercache.batch_get_from_cache([team])
        cached_data, source, cached_etag = batch.get(team.id, (None, "miss", None))

    # Get flags from database - use db_batch_data if available to avoid N+1 queries
    if db_batch_data and team.id in db_batch_data:
        db_data = db_batch_data[team.id]
    else:
        db_data = _get_feature_flags_for_service(team)
    db_flags = db_data.get("flags", []) if isinstance(db_data, dict) else []

    # Cache miss. This verifier reads Redis only (via batch_get_from_cache), so in
    # practice source is "redis" or "miss"; "db"/"dependency_unavailable" are matched
    # defensively to stay in lock-step with verify_team_flag_definitions, which can see
    # them through its single-team cold-load fallback. All mean "nothing cached", not drift.
    if source in ("db", "miss", "dependency_unavailable"):
        return {
            "status": "miss",
            "issue": "CACHE_MISS",
            "details": f"No cache entry found (team has {len(db_flags)} flags in DB)",
            "db_data": db_data,
        }

    # Check if evaluation_metadata is present in cached data.
    # Entries written before evaluation_metadata was added won't have it,
    # and the Rust service needs it for flag dependency evaluation.
    if not cached_data or "evaluation_metadata" not in cached_data:
        return {
            "status": "mismatch",
            "issue": "MISSING_EVALUATION_METADATA",
            "details": "Cache entry missing evaluation_metadata",
            "db_data": db_data,
        }

    # Without an etag, the Rust feature-flags in-memory cache bypasses every
    # request for this team via the `etag_missing` branch. Surfacing this here
    # turns a silent perf regression into a counted verifier mismatch. The
    # etag rides on the same MGET as the payload, so this stays O(1) per batch.
    # Checked before the per-flag diff: a team with both missing etag AND
    # drifted flags reports as MISSING_ETAG; the repair writes db_data back
    # and fixes both, so ordering it first skips the diff loop on rollout
    # when most teams hit this branch with valid data.
    if cached_etag is None:
        return {
            "status": "mismatch",
            "issue": "MISSING_ETAG",
            "details": "Cache entry has payload but no etag — Rust in-memory cache will bypass for this team",
            "db_data": db_data,
        }

    # Extract cached flags
    cached_flags = cached_data.get("flags", [])

    # Compare flags by ID
    db_flags_by_id = {flag["id"]: flag for flag in db_flags}
    cached_flags_by_id = {flag["id"]: flag for flag in cached_flags}

    diffs = []

    # Find missing flags (in DB but not in cache)
    for flag_id in db_flags_by_id:
        if flag_id not in cached_flags_by_id:
            diff: dict = {
                "type": "MISSING_IN_CACHE",
                "flag_id": flag_id,
                "flag_key": db_flags_by_id[flag_id].get("key"),
            }
            diffs.append(diff)

    # Find stale flags (in cache but not in DB)
    for flag_id in cached_flags_by_id:
        if flag_id not in db_flags_by_id:
            diff = {
                "type": "STALE_IN_CACHE",
                "flag_id": flag_id,
                "flag_key": cached_flags_by_id[flag_id].get("key"),
            }
            diffs.append(diff)

    # Compare field values for flags that exist in both
    for flag_id in db_flags_by_id:
        if flag_id in cached_flags_by_id:
            db_flag = db_flags_by_id[flag_id]
            cached_flag = cached_flags_by_id[flag_id]
            field_diffs = _compare_flag_fields(db_flag, cached_flag)
            if field_diffs:
                diff = {
                    "type": "FIELD_MISMATCH",
                    "flag_id": flag_id,
                    "flag_key": db_flag.get("key"),
                    "diff_fields": [f["field"] for f in field_diffs],
                }
                if verbose:
                    diff["field_diffs"] = field_diffs
                diffs.append(diff)

    if not diffs:
        return {"status": "match", "issue": "", "details": ""}

    # Summarize diffs
    missing_count = sum(1 for d in diffs if d.get("type") == "MISSING_IN_CACHE")
    stale_count = sum(1 for d in diffs if d.get("type") == "STALE_IN_CACHE")
    mismatch_count = sum(1 for d in diffs if d.get("type") == "FIELD_MISMATCH")

    summary_parts = []
    if missing_count > 0:
        summary_parts.append(f"{missing_count} missing")
    if stale_count > 0:
        summary_parts.append(f"{stale_count} stale")
    if mismatch_count > 0:
        summary_parts.append(f"{mismatch_count} mismatched")

    # Build descriptive diff_flags for logging
    diff_flags = []
    for d in sorted(diffs, key=lambda x: x.get("flag_key") or str(x["flag_id"])):
        flag_key = d.get("flag_key") or str(d["flag_id"])
        diff_type = d.get("type")
        if diff_type == "MISSING_IN_CACHE":
            diff_flags.append(f"{flag_key} {{only in db}}")
        elif diff_type == "STALE_IN_CACHE":
            diff_flags.append(f"{flag_key} {{only in cache}}")
        elif diff_type == "FIELD_MISMATCH":
            fields = d.get("diff_fields", [])
            diff_flags.append(f"{flag_key} {{fields: {', '.join(fields)}}}")

    result: dict = {
        "status": "mismatch",
        "issue": "DATA_MISMATCH",
        "details": f"{', '.join(summary_parts)} flags" if summary_parts else "unknown differences",
        "diff_flags": diff_flags,
        "db_data": db_data,
    }

    if verbose:
        result["diffs"] = diffs

    return result


# Keys whose ``null`` is semantically distinct from "absent" and must be preserved
# during loose comparison — but only at the group level (``filters.groups[*]`` /
# ``filters.super_groups[*]``), where the Rust matcher uses
# ``Option<Option<i32>>`` with ``skip_serializing_if`` on
# ``FlagPropertyGroup.aggregation_group_type_index`` to distinguish "absent
# (fall back to flag-level group type)" from "explicit null (force person-level
# aggregation)". At the filters level the Rust ``FlagFilters`` field is plain
# ``Option<i32>`` with no ``skip_serializing_if``, so the warmer always emits
# ``null`` for both PG-null and PG-absent; preserving null there would flag
# every PG-absent team as drifted. The list keys below mark the path into
# group-level dicts so preservation only kicks in for those nested entries.
_PRESERVE_NULL_KEYS = frozenset({"aggregation_group_type_index"})
_GROUP_LEVEL_LIST_KEYS = frozenset({"groups", "super_groups"})


def _strip_null_values(value: Any, in_group_level_list: bool = False) -> Any:
    """Recursively drop ``None`` values from dicts; recurse into lists without dropping ``None`` elements.

    Used to normalize structural divergence between the Django serializer (which
    passes JSONB through verbatim and preserves explicit ``null`` entries) and
    the Rust warmer (whose typed ``Option<T>`` deserialization collapses
    "absent key" and "explicit null" into the same ``None`` and emits one
    shape). The matcher already treats those two states as equivalent for most
    fields, so the verifier should mirror that tolerance instead of reporting
    spurious ``FIELD_MISMATCH``.

    Rules:
    - Dicts: drop entries whose value is ``None``, except for keys in
      ``_PRESERVE_NULL_KEYS`` when this dict is a group-level item (sits inside
      ``filters.groups[*]`` or ``filters.super_groups[*]``), where ``null`` is
      semantically distinct from absent; recurse into remaining values, marking
      group-level list values so their dict elements know they're at group level.
    - Lists: recurse into each element, but preserve ``None`` elements (dropping
      them would shift indices and change semantics). The Rust typed
      serialization will not emit ``null`` list elements in current data, so
      this rule preserves correctness without changing observed behavior.
    - Scalars: returned unchanged.

    See plans/verify-flags-cache-loose-comparison.md for the full rationale.
    """
    if isinstance(value, dict):
        return {
            k: _strip_null_values(v, in_group_level_list=(k in _GROUP_LEVEL_LIST_KEYS))
            for k, v in value.items()
            if v is not None or (in_group_level_list and k in _PRESERVE_NULL_KEYS)
        }
    if isinstance(value, list):
        return [_strip_null_values(item, in_group_level_list=in_group_level_list) for item in value]
    return value


def _compare_flag_fields(db_flag: dict, cached_flag: dict) -> list[dict]:
    """Compare field values between DB and cached versions of a flag.

    The DB serialization is treated as the source of truth: only keys present in
    ``db_flag`` are compared. Extra keys in ``cached_flag`` (e.g. fields that
    were removed from the serializer but still linger in pre-existing cache
    entries) are ignored so that benign serializer field removals do not flag
    every team's cache as mismatched.

    For container values (dicts and lists, which is where every observed
    absent/null divergence lives — under ``filters``), both sides are passed
    through ``_strip_null_values`` before the equality check so that explicit
    ``null`` and absent-key normalize to the same shape. Top-level scalar keys
    are compared directly; ``MinimalFeatureFlagSerializer`` emits all top-level
    keys explicitly today, so there is no top-level absent/null divergence to
    tolerate. See plans/verify-flags-cache-loose-comparison.md.
    """
    field_diffs = []

    for key in db_flag.keys():
        db_val = db_flag[key]
        cached_val = cached_flag.get(key)

        if isinstance(db_val, dict | list) or isinstance(cached_val, dict | list):
            if _strip_null_values(db_val) != _strip_null_values(cached_val):
                field_diffs.append({"field": key, "db_value": db_val, "cached_value": cached_val})
        elif db_val != cached_val:
            field_diffs.append({"field": key, "db_value": db_val, "cached_value": cached_val})

    return field_diffs


def get_teams_with_flags_queryset() -> "QuerySet[Team]":
    """
    Return a queryset of teams that have ever had a feature flag.

    Queries via ``objects_including_soft_deleted`` so that teams whose flags
    were all soft-deleted still get their cache verified (the cache should
    contain ``{"flags": []}``, not be absent).

    Used as the single source of truth for scoping both Celery verification
    tasks and management commands to the ~10% of teams that have flags.
    """
    # Use Q() to pass team_id as a positional arg, bypassing RootTeamQuerySet.filter()
    # which intercepts team_id kwargs and adds expensive parent-team JOIN/subquery logic
    # that makes the correlated EXISTS subquery unusable at scale.
    has_flags = FeatureFlag.objects_including_soft_deleted.filter(Q(team_id=OuterRef("pk")))
    return Team.objects.filter(Exists(has_flags))


def get_team_ids_with_recently_updated_flags(team_ids: list[int]) -> set[int]:
    """
    Batch check which teams have active flags updated within the grace period.

    When a flag is updated, an async task updates the cache. If verification
    runs before the async task completes, it sees a stale cache and tries to
    "fix" it, causing unnecessary work. This grace period lets recent async
    updates complete before treating cache misses as genuine errors.

    Only considers active, non-deleted flags. When a flag is deleted or
    deactivated, the cache update removes it, so we shouldn't skip verification
    just because a deleted/inactive flag was recently updated.

    Args:
        team_ids: List of team IDs to check

    Returns:
        Set of team IDs that have recently updated active flags (should skip fix)
    """
    grace_period_minutes = settings.FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES
    if grace_period_minutes <= 0 or not team_ids:
        return set()

    cutoff = timezone.now() - timedelta(minutes=grace_period_minutes)
    return set(
        FeatureFlag.objects.filter(team_id__in=team_ids, updated_at__gte=cutoff, active=True)
        .values_list("team_id", flat=True)
        .distinct()
    )


# Initialize hypercache management config after update_flags_cache is defined
FLAGS_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=flags_hypercache,
    update_fn=update_flags_cache,
    cache_name="flags",
    get_teams_queryset_fn=get_teams_with_flags_queryset,
    get_team_ids_to_skip_fix_fn=get_team_ids_with_recently_updated_flags,
)


def clear_flags_cache(team: Team | int, kinds: list[str] | None = None) -> None:
    """
    Clear the flags cache for a team.

    Only operates when FLAGS_REDIS_URL is configured to avoid writing to shared cache.

    Args:
        team: Team object or team ID
        kinds: Optional list of cache kinds to clear ("redis", "s3")
    """
    if not settings.FLAGS_REDIS_URL:
        return

    flags_hypercache.clear_cache(team, kinds=kinds)


def get_teams_with_expiring_flags_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> list[Team]:
    """
    Get teams whose flags caches are expiring soon using sorted set for efficient lookup.

    Uses ZRANGEBYSCORE on the expiry tracking sorted set instead of scanning all Redis keys.
    This is O(log N + M) where M is the number of expiring teams, vs O(N) for SCAN.

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to return (default 5000)

    Returns:
        List of Team objects whose caches need refresh (up to limit)
    """
    return get_teams_with_expiring_caches(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def refresh_expiring_flags_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> tuple[int, int]:
    """
    Refresh flags caches that are expiring soon to prevent cache misses.

    This is the main hourly job that keeps caches fresh. It:
    1. Finds cache entries with TTL < threshold (up to limit)
    2. Refreshes them with new data and full TTL

    Processes teams in batches (default 5000). If more teams are expiring than the limit,
    subsequent runs will process the next batch.

    Note: Metrics are pushed to Pushgateway by refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

    Args:
        ttl_threshold_hours: Refresh caches expiring within this many hours
        limit: Maximum number of teams to refresh per run (default 5000)
               5000 chosen as starting point to balance:
               - Memory efficiency: Doesn't load too many teams into memory at once
               - Throughput: With ~200K teams total, hourly runs can process 120K/day (5000 * 24)
               - Responsiveness: Completes quickly enough to not block other operations

    Returns:
        Tuple of (successful_refreshes, failed_refreshes)
    """
    return refresh_expiring_caches(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def cleanup_stale_expiry_tracking() -> int:
    """
    Clean up orphaned entries in the expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Should be run periodically (e.g., daily) to prevent sorted set bloat.

    Returns:
        Number of stale entries removed
    """
    removed = cleanup_generic(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG)

    if removed > 0:
        TOMBSTONE_COUNTER.labels(
            namespace="flags",
            operation="stale_expiry_tracking",
            component="flags_cache",
        ).inc(removed)

    return removed


def get_cache_stats() -> dict[str, Any]:
    """
    Get statistics about the flags cache.

    Returns:
        Dictionary with cache statistics including size information
    """
    return get_cache_stats_generic(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG)


# Signal handlers for automatic cache invalidation


# KAFKA-CUTOVER TRANSITIONAL CODE — remove at cutover.
# Stages: producer (this block) at 0% → Rust consumer ships → ramp gate to 100%
# → Kafka becomes primary, this block is deleted and the signal handlers call
# the Kafka path directly. The Celery task `update_team_service_flags_cache`
# outlives cutover — `cohort_changed_flags_cache` still calls it directly until
# cohort invalidation gets its own topic. Throwaway code by design; don't polish.
#
# Transitional surface: KAFKA_ROUTING_FLAG, _route_to_kafka,
# _produce_invalidation, _enqueue_invalidation, and the Kafka branch inside it.
# The signal handlers themselves stay; their tails simplify at cutover.

# Per-team gate that routes invalidation to Kafka instead of Celery — see
# _enqueue_invalidation for why the two paths are mutually exclusive. The key
# string is kept as "dual-write" (not renamed to match KAFKA_ROUTING_FLAG) since
# it's the live PostHog flag key — renaming it would repoint the rollout.
KAFKA_ROUTING_FLAG = "flags-cache-kafka-dual-write"


def _route_to_kafka(team_id: int) -> bool:
    """Return True if this team's invalidation should route to Kafka instead of Celery.

    A `None` return from `feature_enabled` means the local-eval cache hasn't
    loaded the flag definition yet. Treated as disabled, but ticks
    TOMBSTONE_COUNTER so a fleet-wide silent disable (polling thread wedged)
    is visible on existing Grafana dashboards: a short burst at boot is
    expected; a sustained non-zero rate means polling is broken.
    """
    try:
        # The SDK annotates feature_enabled as returning bool, but it returns
        # None when local evaluation can't resolve the flag. Widen the type so
        # the None branch below survives type checking.
        result: bool | None = posthoganalytics.feature_enabled(
            KAFKA_ROUTING_FLAG,
            f"team-{team_id}",
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        # If the flag client misbehaves, default to Celery-only — never block the signal handler.
        # Log so a silent disable across the fleet during rollout is visible in Sentry.
        logger.warning(
            # Event name kept as "dual_write" (not renamed to match KAFKA_ROUTING_FLAG) so it
            # keeps matching existing Sentry searches set up during the dual-write phase.
            "flags_cache_kafka_dual_write_flag_evaluation_failed",
            team_id=team_id,
            flag=KAFKA_ROUTING_FLAG,
            exc_info=True,
        )
        return False

    if result is None:
        TOMBSTONE_COUNTER.labels(
            namespace="flags",
            # Label kept as "dual_write" for continuity with the existing Grafana dashboards
            # referenced above.
            operation="dual_write_gate_cache_cold",
            component="flags_cache",
        ).inc()
        return False

    return bool(result)


def _produce_invalidation(team_id: int) -> None:
    """Produce a single invalidation message; swallow Kafka errors.

    A produce failure here must not raise out of a signal handler — see
    `_enqueue_invalidation` for why that means the invalidation is dropped
    rather than retried via Celery. Per-message delivery success/failure is
    also counted in KAFKA_PRODUCER_MESSAGES_COUNTER (wired in `_KafkaProducer.produce`).

    `data` must be a dict (not pre-encoded bytes): `_KafkaProducer.produce`
    runs it through `json_serializer` (`json.dumps` + utf-8 encode). Passing
    bytes would `TypeError` inside `json.dumps` and silently fail the swallow
    path. `mode="json"` converts `datetime` to ISO string.

    `flush_timeout=0` keeps this off the request hot path — librdkafka's
    background thread drains the singleton's queue, and the next call flushes
    again. A blocking flush would stall every flag-edit on-commit hook on an
    unhealthy cluster.
    """
    try:
        msg = FlagsCacheInvalidation(team_id=team_id, emitted_at=datetime.now(UTC))
        with producer_scope(topic=KAFKA_FLAGS_CACHE_INVALIDATION, flush_timeout=0) as producer:
            producer.produce(
                topic=KAFKA_FLAGS_CACHE_INVALIDATION,
                data=msg.model_dump(mode="json"),
                key=str(team_id),
            )
    except Exception as e:
        logger.warning("flags_cache_invalidation_produce_failed", team_id=team_id, error=str(e), exc_info=True)


def _enqueue_invalidation(team_id: int) -> None:
    """Run from `transaction.on_commit`: route to Kafka if enabled, otherwise Celery.

    Model signal handlers wrap this in `transaction.on_commit`: deferring until commit
    avoids race conditions where the Celery worker reads pre-commit state. Callers with no
    open transaction to defer past (e.g. staff tooling, via `enqueue_evaluation_cache_invalidation`)
    call it directly. Shared by all four signal handlers wired to the flag-invalidation topic.
    Cohort invalidation is intentionally not routed here, since cohort changes flow through their
    own topic.

    The two paths are mutually exclusive so the rollout proves the Kafka path
    actually works end to end: Celery is not a fallback when the flag is on,
    so a stuck Kafka producer shows up as a stale cache for that team instead
    of being masked by Celery quietly picking up the slack. `_produce_invalidation`
    still swallows its own errors — a produce failure must not raise out of a
    signal handler — but for a flagged team that failure means the invalidation
    is dropped, not retried via Celery. Watch `flags_cache_invalidation_produce_failed`
    logs during rollout. Celery's `.delay()` is allowed to raise when the flag
    is off — it's the sole path in that case and operators want broker failures loud.

    Guarded on FLAGS_REDIS_URL here (not just at each call site) so every caller, including
    ones outside a signal handler, gets the same no-op-when-unconfigured behavior for free.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    from products.feature_flags.backend.tasks import update_team_service_flags_cache

    if _route_to_kafka(team_id):
        _produce_invalidation(team_id)
    else:
        update_team_service_flags_cache.delay(team_id)


def enqueue_evaluation_cache_invalidation(team_id: int) -> None:
    """Public entry point for `_enqueue_invalidation`, for callers outside a model signal handler
    (e.g. staff tooling) that want a rebuild to raise the exact same invalidation signal (Kafka
    or Celery routing) that an organic flag create/update/delete raises."""
    _enqueue_invalidation(team_id)


@receiver(post_save, sender=FeatureFlag)
@receiver(post_delete, sender=FeatureFlag)
def feature_flag_changed_flags_cache(sender, instance: "FeatureFlag", **kwargs):
    """
    Invalidate flags cache when a feature flag is created, updated, or deleted.

    This ensures the feature-flags service always has fresh flag data after any flag changes.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    team_id = instance.team_id
    transaction.on_commit(lambda: _enqueue_invalidation(team_id))


@receiver(post_save, sender=Experiment)
@receiver(post_delete, sender=Experiment)
def experiment_changed_flags_cache(sender, instance: "Experiment", **kwargs):
    """
    Invalidate flags cache when an experiment is created, soft-deleted, or removed.

    A flag's cached `has_experiment` depends on whether it has any non-deleted linked
    experiment, so experiment changes must refresh the linked flag's team cache.
    Keyed on the experiment's own team_id, which also covers experiment reassignment
    between flags within the team. Only operates when FLAGS_REDIS_URL is configured.

    Fires on every save by design, mirroring feature_flag_changed_flags_cache: Experiment
    rows are only written on user-driven lifecycle/edit operations (no high-churn periodic
    path touches them, unlike cohort recalculation), so an update_fields gate isn't warranted.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    team_id = instance.team_id
    transaction.on_commit(lambda: _enqueue_invalidation(team_id))


@receiver(post_save, sender=Team)
def team_created_flags_cache(sender, instance: "Team", created: bool, **kwargs):
    """
    Warm flags cache when a team is created.

    This ensures the cache is immediately available for new teams.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not created or not settings.FLAGS_REDIS_URL:
        return

    team_id = instance.id
    transaction.on_commit(lambda: _enqueue_invalidation(team_id))


@receiver(post_delete, sender=Team)
def team_deleted_flags_cache(sender, instance: "Team", **kwargs):
    """
    Clear flags cache when a team is deleted.

    This ensures we don't have stale cache entries for deleted teams.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    # For unit tests, only clear Redis to avoid S3 timestamp issues with frozen time
    kinds = ["redis"] if settings.TEST else None
    clear_flags_cache(instance, kinds=kinds)


@receiver(post_save, sender=FeatureFlagEvaluationContext)
@receiver(post_delete, sender=FeatureFlagEvaluationContext)
def evaluation_context_changed_flags_cache(sender, instance: "FeatureFlagEvaluationContext", **kwargs):
    """
    Invalidate flags cache when evaluation contexts are added or removed from a flag.

    Evaluation context names are cached as part of the flag data, so changes to the
    FeatureFlagEvaluationContext join table require a cache refresh.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    team_id = instance.feature_flag.team_id
    transaction.on_commit(lambda: _enqueue_invalidation(team_id))


@receiver(post_save, sender=Cohort)
@receiver(post_delete, sender=Cohort)
def cohort_changed_flags_cache(sender, instance: "Cohort", **kwargs):
    """
    Invalidate flags cache when a cohort definition changes.

    Skips recalculation-only saves (count, version, is_calculating, etc.) to avoid
    rebuilding the flags cache on every static cohort recalculation.
    Only operates when FLAGS_REDIS_URL is configured.
    """
    if not settings.FLAGS_REDIS_URL:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and frozenset(update_fields) <= _COHORT_RECALCULATION_FIELDS:
        return

    from products.feature_flags.backend.tasks import update_team_service_flags_cache

    # Intentionally bypasses _enqueue_invalidation: cohort changes do not
    # share the flag-invalidation Kafka topic.
    transaction.on_commit(lambda: update_team_service_flags_cache.delay(instance.team_id))
