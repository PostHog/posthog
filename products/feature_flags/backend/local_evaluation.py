"""
Flag Definitions HyperCache for SDK local evaluation.

This module provides a HyperCache that stores feature flag definitions for SDKs to use
in local evaluation. Unlike the flags_cache.py which provides raw flag data for the
Rust feature-flags service, this provides rich data including full cohort definitions
and group type mappings.

Cache Key Pattern:
- Uses team_id as the key (ID-based cache)
- Stored in both Redis and S3 via HyperCache

Configuration:
- Redis TTL: 7 days (configurable via FLAGS_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via FLAGS_CACHE_MISS_TTL env var)
"""

import time
from collections import defaultdict
from itertools import groupby
from typing import Any, cast

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from posthoganalytics import capture_exception
from prometheus_client import Counter
from rest_framework.exceptions import ValidationError

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.dataclasses import frozen
from posthog.models.group_type_mapping import (
    GROUP_TYPES_STALE_CACHE_KEY_PREFIX,
    GroupTypesUnavailable,
    get_group_types_for_projects,
    project_has_group_types_authoritatively,
)
from posthog.models.team import Team
from posthog.storage.hypercache import (
    HYPERCACHE_REBUILD_SKIPPED_COUNTER,
    HyperCache,
    HyperCacheDependencyUnavailable,
    KeyType,
    emit_cache_sync_metrics,
)
from posthog.storage.hypercache_manager import HyperCacheManagementConfig
from posthog.utils import capture_exception_throttled, get_safe_cache, safe_int

from products.cohorts.backend.models.cohort import Cohort, is_cohort_recalculation_only_save
from products.experiments.backend.models.experiment import Experiment, live_experiment_exists
from products.feature_flags.backend.cache_keys import EU_CROSS_REGION_MIRROR_CACHE_KEY
from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.references import flag_dependency_properties, referenced_cohort_ids
from products.feature_flags.backend.flags_cache import (
    _compare_flag_fields,
    get_team_ids_with_recently_updated_flags,
    get_teams_with_flags_queryset,
)
from products.feature_flags.backend.legacy_definitions import (
    cohort_references,
    drop_legacy_dependents,
    validate_legacy_filters,
)
from products.feature_flags.backend.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.team_feature_flags_config import (
    PropertyMatchingVersion,
    TeamFeatureFlagsConfig,
)
from products.feature_flags.backend.types import FlagProperty
from products.surveys.backend.models import Survey

logger = structlog.get_logger(__name__)


# Sorted set key for tracking cache expirations
FLAG_DEFINITIONS_CACHE_EXPIRY_SORTED_SET = "flag_definitions_cache_expiry"

# Metric to track flags dropped during batch processing due to errors
FLAG_PROCESSING_ERROR_COUNTER = Counter(
    "posthog_flag_definitions_processing_error",
    "Number of flags dropped from cache due to processing errors",
)

# Rebuilds vetoed because the freshly built group_type_mapping was empty over
# populated data. group_type_mapping is a feature-flags concept, so the counter lives
# here rather than in the generic storage layer. The namespace label is kept for
# wire compatibility even though this guard only ever runs for "feature_flags".
HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER = Counter(
    "posthog_hypercache_group_mapping_emptied",
    "Rebuilds skipped because the freshly built group_type_mapping was empty over populated data",
    labelnames=["namespace"],
)


def _resolve_flag_dependency_key(flag_prop: FlagProperty, flag_id_to_key: dict[str, str]) -> str:
    """
    Convert flag property reference to flag key.
    Handles both flag IDs and flag keys as references.
    """
    flag_reference = str(flag_prop.get("key", ""))
    return flag_id_to_key.get(flag_reference, flag_reference)


class _DependencyChainBuilder:
    """
    Internal class for building flag dependency chains using topological sorting.

    Encapsulates the complex DFS logic and state management needed for dependency chain
    computation while providing memoization for performance.
    """

    def __init__(self, all_flags: dict[str, Any]):
        self.all_flags = all_flags
        self.memo: dict[str, list[str]] = {}

    def build_chain(self, flag_key: str) -> list[str]:
        """
        Build the dependency chain for a single flag using topological sorting.
        Returns a list of flag keys in the order they should be evaluated.

        Handles circular dependencies by detecting cycles and logging warnings.
        When a cycle is detected, returns an empty array since the flag cannot be safely evaluated.
        """
        if flag_key in self.memo:
            return self.memo[flag_key]

        if self._has_self_dependency(flag_key):
            logger.warning(
                "Self-dependency detected in feature flag",
                extra={"flag_key": flag_key},
            )
            self.memo[flag_key] = []
            return []

        chain = self._dfs(flag_key)
        if chain is None:
            logger.warning(
                "Flag cannot be evaluated due to circular dependencies or missing dependencies",
                extra={"flag_key": flag_key},
            )
            self.memo[flag_key] = []
            return []

        self.memo[flag_key] = chain
        return chain

    def _has_self_dependency(self, flag_key: str) -> bool:
        """Check if a flag has a direct self-dependency."""
        flag_data = self.all_flags.get(flag_key)
        if not flag_data:
            return False

        filters = flag_data.get("filters", {})
        for flag_prop in flag_dependency_properties(filters):
            dep_flag_key = flag_prop["key"]  # Already normalized to key
            if dep_flag_key == flag_key:
                return True
        return False

    def _dfs(self, root_key: str) -> list[str] | None:
        """Return the evaluation order for ``root_key``, or None for a cycle or missing dependency."""
        visited: set[str] = set()
        temp_visited: set[str] = set()
        chain: list[str] = []
        # Iterative DFS keeps a deep dependency chain from exhausting Python's call stack.
        pending = [(root_key, False)]
        while pending:
            key, leaving = pending.pop()
            if leaving:
                temp_visited.remove(key)
                visited.add(key)
                chain.append(key)
                continue
            if key in temp_visited:
                logger.warning("Circular dependency detected in feature flags", extra={"circular_at": key})
                return None
            if key in visited:
                continue
            if not self._validate_flag_exists(key):
                return None
            temp_visited.add(key)
            pending.append((key, True))
            dependencies = flag_dependency_properties(self.all_flags[key].get("filters", {}))
            for prop in reversed(dependencies):
                dependency = prop["key"]
                if dependency == key:
                    continue
                if dependency not in self.all_flags:
                    logger.warning(
                        "Flag dependency references non-existent flag",
                        extra={"flag": key, "missing_dependency": dependency},
                    )
                    return None
                pending.append((dependency, False))
        return chain

    def _validate_flag_exists(self, flag_key: str) -> bool:
        """Validate that a flag exists in the flags collection."""
        if flag_key not in self.all_flags:
            logger.warning(
                "Attempting to build dependency chain for non-existent flag",
                extra={"flag_key": flag_key},
            )
            return False
        return True


def _normalize_and_collect_dependency_target_keys(
    flags_data: list[dict[str, Any]], flag_id_to_key: dict[str, str]
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    Normalize flag properties and collect dependency target keys.

    Args:
        flags_data: List of flag data dictionaries to process
        flag_id_to_key: Mapping from flag IDs to flag keys

    Returns:
        tuple: (normalized_flags_data, unique_dependency_target_keys)
    """
    unique_dependencies = set()

    for flag_data in flags_data:
        filters = flag_data.get("filters", {})
        for flag_prop in flag_dependency_properties(filters):
            # Transform flag ID to flag key
            flag_key = _resolve_flag_dependency_key(flag_prop, flag_id_to_key)
            flag_prop["key"] = flag_key
            # Collect unique dependency at the same time
            unique_dependencies.add(flag_key)

    return flags_data, unique_dependencies


def _build_all_dependency_chains(
    flags_data: list[dict[str, Any]], unique_dependencies: set[str]
) -> list[dict[str, Any]]:
    """
    Final pass: Build dependency chains for all flag properties using pre-collected dependencies.
    Assumes flag IDs have already been normalized to keys and dependencies collected.
    Uses optimized batch processing with memoization to avoid rebuilding chains for shared dependencies.
    """
    if not unique_dependencies:
        return flags_data

    all_flags_by_key = {flag["key"]: flag for flag in flags_data}

    builder = _DependencyChainBuilder(all_flags_by_key)

    for dep_key in unique_dependencies:
        # This will populate the builder's cache
        builder.build_chain(dep_key)

    for flag_data in flags_data:
        filters = flag_data.get("filters", {})

        for flag_prop in flag_dependency_properties(filters):
            flag_key = flag_prop["key"]

            dependency_chain = builder.build_chain(flag_key)

            # The dependency chain represents the order in which flags should be evaluated
            # It includes the target flag and its dependencies in topological order
            # Always add the dependency_chain property, even if empty (for self-dependencies, missing dependencies, etc.)
            flag_prop["dependency_chain"] = dependency_chain

    return flags_data


def _transform_flag_property_dependencies(
    flags_data: list[dict[str, Any]], flag_id_to_key: dict[str, str]
) -> list[dict[str, Any]]:
    """
    Transform flag properties in filter conditions to include dependency chains.
    Uses an optimized two-pass approach:
    1. Normalize flag IDs to keys and collect unique dependency target keys in single pass
    2. Build dependency chains for collected dependency targets using batch processing

    Args:
        flags_data: List of serialized flag dictionaries to transform
        flag_id_to_key: Mapping from flag ID (as string) to flag key
    """
    flags_data, unique_dependencies = _normalize_and_collect_dependency_target_keys(flags_data, flag_id_to_key)

    flags_data = _build_all_dependency_chains(flags_data, unique_dependencies)

    return flags_data


def _apply_flag_dependency_transformation(
    response_data: dict[str, Any], flag_id_to_key: dict[str, str]
) -> dict[str, Any]:
    """
    Apply flag dependency transformation to response data.

    This method transforms flag properties in filter conditions to include dependency chains,
    enabling simple client-side evaluation without complex graph construction.

    Args:
        response_data: The response data containing flags to transform
        flag_id_to_key: Mapping from flag ID (as string) to flag key

    Returns:
        New response data dictionary with transformed flags
    """
    flags_list = cast(list[dict[str, Any]], response_data["flags"])
    transformed_flags = _transform_flag_property_dependencies(flags_list, flag_id_to_key)
    return {**response_data, "flags": transformed_flags}


DATABASE_FOR_LOCAL_EVALUATION = (
    "default"
    if ("local_evaluation" not in settings.READ_REPLICA_OPT_IN or "replica" not in settings.DATABASES)  # noqa: F821
    else "replica"
)


def _load_flag_definitions_with_cohorts(key: KeyType) -> dict[str, Any]:
    if key == EU_CROSS_REGION_MIRROR_CACHE_KEY:
        # No DB row backs this key — it's a pure cache mirror written only by
        # cross_region_flag_sync's periodic task. A cold cache should wait for the
        # next sync tick, not attempt (and fail) a Team lookup. Raising (rather than
        # returning HyperCacheStoreMissing) avoids caching a day-long miss sentinel
        # and deleting the ETag, which could shadow a concurrent sync write.
        raise HyperCacheDependencyUnavailable(f"{EU_CROSS_REGION_MIRROR_CACHE_KEY} not yet synced")
    return _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key))


def _build_flag_definitions_hypercache() -> HyperCache:
    has_dedicated_cache = FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES
    return HyperCache(
        namespace="feature_flags",
        value="flags_with_cohorts.json",
        load_fn=_load_flag_definitions_with_cohorts,
        cache_ttl=settings.FLAGS_CACHE_TTL,
        cache_miss_ttl=settings.FLAGS_CACHE_MISS_TTL,
        batch_load_fn=lambda teams: _get_flags_response_for_local_evaluation_batch(teams),
        enable_etag=True,
        expiry_sorted_set_key=FLAG_DEFINITIONS_CACHE_EXPIRY_SORTED_SET,
        cache_alias=FLAGS_DEDICATED_CACHE_ALIAS if has_dedicated_cache else None,
        # Mirror to the shared Redis while the /flags/definitions reader still reads
        # from it.
        secondary_cache_alias="default" if has_dedicated_cache else None,
    )


flag_definitions_hypercache = _build_flag_definitions_hypercache()


def _resolve_team(team: Team | int) -> Team | None:
    """Resolve a Team object or ID to a Team, returning None if not found."""
    if isinstance(team, int):
        try:
            return Team.objects.get(id=team)
        except Team.DoesNotExist:
            logger.warning("Team not found for flag definitions cache update", team_id=team)
            return None
    return team


def update_flag_definitions_cache(team: Team | int, ttl: int | None = None) -> bool:
    """
    Update the flag definitions cache for a team.

    Delegates to HyperCache.update_cache() which handles error logging and sync metrics.

    Args:
        team: Team object or team ID
        ttl: Optional custom TTL in seconds (defaults to FLAGS_CACHE_TTL)

    Returns:
        True if the cache update succeeded, False otherwise
    """
    resolved_team = _resolve_team(team)
    if resolved_team is None:
        return False

    return flag_definitions_hypercache.update_cache(resolved_team, ttl=ttl)


# Throttle window for capturing skipped rebuilds, shared across processes via the
# cache so many workers skipping at once report at most once per window.
_FLAG_CACHE_SKIP_CAPTURE_THROTTLE_TTL = 60  # seconds


def _capture_flag_cache_skip_throttled(throttle_key: str, exc: BaseException, message: str, **log_fields: Any) -> None:
    """Log a skipped flag-cache rebuild and capture the exception, throttling the
    capture across processes. Each log line records whether the capture ran or was
    throttled."""
    captured = capture_exception_throttled(throttle_key, exc, _FLAG_CACHE_SKIP_CAPTURE_THROTTLE_TTL)
    logger.error(message, exception_captured=captured, capture_throttled=not captured, **log_fields)


def _group_mapping_would_be_emptied(team: Team, payload: dict[str, Any]) -> bool:
    """True when writing this payload would replace a populated group_type_mapping
    with an empty one.

    An empty freshly built mapping is correct for a team with no group types but is
    the symptom of a silent upstream failure for a team that has them. The per-project
    stale key is the cheap last-known-good signal; when it is absent (never populated,
    expired, or deleted by a concurrent invalidate_group_types_cache) we confirm
    against the persons-DB primary, so the check cannot be defeated by stale-key
    timing.
    """
    if payload.get("group_type_mapping"):
        return False
    if get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{team.project_id}"):
        return True
    return project_has_group_types_authoritatively(team.project_id)


def _skip_write_if_group_mapping_emptied(key: KeyType, payload: dict[str, Any]) -> bool:
    """Veto a flag-definitions write that would empty a populated group_type_mapping,
    emitting the skip metric + throttled capture. Shared by every write path — the
    signal-driven rebuild and the refresh/warm update_cache path — so the guard can't
    be bypassed depending on which trigger fired."""
    team = HyperCache.team_from_key(key)
    if not _group_mapping_would_be_emptied(team, payload):
        return False
    HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER.labels(namespace="feature_flags").inc()
    _capture_flag_cache_skip_throttled(
        "flag_cache_group_mapping_emptied_capture_throttle",
        # Keep team.id out of the message so error tracking groups every team's skip into
        # one issue instead of spawning a separate issue per team. The team is on the log
        # line below for debugging.
        Exception("group_type_mapping would be emptied for a team with populated group types"),
        "Skipped feature_flags cache rebuild: refusing to empty a populated group_type_mapping",
        team_id=team.id,
    )
    return True


def update_flag_caches(team: Team):
    """Update the flag definitions cache."""
    logger.info("Syncing feature_flags cache for team", team_id=team.id)

    start_time = time.time()
    success = False
    size: int | None = None
    try:
        payload = _get_flags_response_for_local_evaluation(team)

        if _skip_write_if_group_mapping_emptied(team, payload):
            return

        # Signal-driven rebuilds skip the write when the payload is unchanged: most
        # saves that trigger this (notably the nightly cohort recalculation) don't alter
        # flag definitions, so the ETag is identical and a rewrite would only add load.
        size = flag_definitions_hypercache.set_cache_value(team, payload, skip_if_unchanged=True)

        success = True
    except GroupTypesUnavailable as e:
        # Group types could not be loaded; skip the write to keep the existing entry.
        HYPERCACHE_REBUILD_SKIPPED_COUNTER.labels(namespace="feature_flags", reason="group_types_unavailable").inc()
        _capture_flag_cache_skip_throttled(
            "flag_cache_group_types_unavailable_capture_throttle",
            e,
            "Skipped feature_flags cache rebuild: group types unavailable",
            team_id=team.id,
        )
        return
    except Exception as e:
        capture_exception(e)
        logger.exception("Failed to sync feature_flags cache for team", team_id=team.id, exception=str(e))
    finally:
        duration = time.time() - start_time
        result = "success" if success else "failure"
        emit_cache_sync_metrics(
            result, "feature_flags", "flags_local_eval.json", duration=duration, increment_counter=False
        )
        emit_cache_sync_metrics(result, "feature_flags", "flags_with_cohorts.json", size=size)


def clear_flag_definition_caches(team: KeyType, kinds: list[str] | None = None):
    """
    Clear the flag definitions cache for a team (or the EU cross-region mirror sentinel).

    Clears from shared cache and removes from expiry tracking.
    Expiry tracking cleanup is handled by HyperCache.clear_cache() internally.
    """
    flag_definitions_hypercache.clear_cache(team, kinds=kinds)


def _local_eval_response(
    *,
    flags: list[dict[str, Any]],
    group_type_mapping: dict[str, str],
    cohorts: dict[str, Any],
    minimal_flag_called_events: bool,
    property_matching_version: int,
) -> dict[str, Any]:
    return {
        "flags": flags,
        "group_type_mapping": group_type_mapping,
        "cohorts": cohorts,
        "minimal_flag_called_events": minimal_flag_called_events,
        "property_matching_version": property_matching_version,
    }


def _get_flags_response_for_local_evaluation(team: Team) -> dict[str, Any]:
    """Build the local-evaluation response for a single team."""
    results = _get_flags_response_for_local_evaluation_batch([team])
    if team.id not in results:
        raise RuntimeError(f"Flag definitions build failed for team {team.id}")
    return results[team.id]


# Errors that mean a stored flag or cohort definition is malformed.
_MALFORMED_DEFINITION_ERRORS = (AttributeError, TypeError, ValueError, KeyError, RecursionError, ValidationError)


def _is_supported_legacy_flag(flag: FeatureFlag) -> bool:
    try:
        validate_legacy_filters(flag.filters)
        return True
    except ConfigFormatError:
        return False
    except (TypeError, ValueError):
        logger.warning(
            "Malformed feature flag omitted from legacy definitions",
            extra={"team_id": flag.team_id, "flag_id": flag.pk},
            exc_info=True,
        )
        FLAG_PROCESSING_ERROR_COUNTER.inc()
        return False


@frozen
class _LegacyCohortDefinition:
    properties: dict[str, Any]
    dependencies: set[int]


def _serialize_legacy_cohort(cohort: Cohort) -> _LegacyCohortDefinition:
    """Validate raw properties because Filter can turn untyped groups into empty
    AND groups and drop unparseable properties, hiding malformed cohort data.

    Keep the serialized properties with their references so all flags sharing a
    cohort use the same validated definition without repeating model conversion.
    """
    if cohort.filters is not None and not isinstance(cohort.filters, dict):
        raise ValueError("Invalid legacy cohort filters")
    references = None
    if cohort.filters and cohort.filters.get("properties") is not None:
        properties = cohort.filters["properties"]
        if isinstance(properties, list):
            properties = {"type": "AND", "values": properties}
        # Filter keeps every entry of a flat {property: value} dictionary, so its serialized form can be validated.
        is_flat_legacy_dict = isinstance(properties, dict) and not ("type" in properties and "values" in properties)
        if not is_flat_legacy_dict:
            references = cohort_references(properties)
    serialized = cohort.properties.to_dict()
    if references is None:
        references = cohort_references(serialized)
    return _LegacyCohortDefinition(properties=serialized, dependencies={int(reference) for reference in references})


def _flag_cohort_ids(
    filters: dict[str, Any],
    project_cohorts: dict[int, Cohort],
    definitions: dict[int, _LegacyCohortDefinition],
    malformed: set[int],
) -> set[int]:
    cohort_ids: set[int] = set()
    pending = list(referenced_cohort_ids(filters))
    while pending:
        cid = pending.pop()
        if cid not in project_cohorts or cid in cohort_ids:
            continue
        if cid in malformed:
            raise ValueError("Malformed cohort in legacy flag definition")
        cohort_ids.add(cid)
        pending.extend(definitions[cid].dependencies)
    return cohort_ids


def _get_flags_response_for_local_evaluation_batch(teams: list[Team]) -> dict[int, dict[str, Any]]:
    """
    Build local-evaluation responses for multiple teams using bulk data loading.

    Loads survey flag IDs, eligible flags, excluded flag references, cohorts, and
    group type mappings in bulk, then processes one team's flags at a time. A team
    whose own build fails is left out, so callers keep its previous cache entry.
    """
    from products.feature_flags.backend.api.feature_flag import EvaluationFeatureFlagSerializer

    if not teams:
        return {}

    team_ids = [t.id for t in teams]
    team_by_id = {t.id: t for t in teams}
    project_ids = list({t.project_id for t in teams})

    # Local-evaluation SDKs never call /flags, so team rollout settings must travel in
    # this blob. Missing config rows retain both legacy behaviors.
    team_config_by_team_id = {
        team_id: (minimal_flag_called_events, property_matching_version)
        for team_id, minimal_flag_called_events, property_matching_version in TeamFeatureFlagsConfig.objects.db_manager(
            DATABASE_FOR_LOCAL_EVALUATION
        )
        .filter(team_id__in=team_ids)
        .values_list("team_id", "minimal_flag_called_events", "property_matching_version")
    }

    # Bulk load survey flag IDs across all teams
    survey_flag_ids: set[int] = set()
    for row in (
        Survey.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(team_id__in=team_ids)
        .values_list(
            "targeting_flag_id",
            "internal_targeting_flag_id",
            "internal_response_sampling_flag_id",
        )
    ):
        survey_flag_ids.update(fid for fid in row if fid is not None)

    flag_queryset = FeatureFlag.objects_including_soft_deleted.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
        team_id__in=team_ids
    )
    ineligible = Q(deleted=True) | Q(has_encrypted_payloads=True) | Q(pk__in=survey_flag_ids)
    excluded_by_team: dict[int, dict[str, str]] = defaultdict(dict)
    # Preserve ordering for groupby and ETag stability.
    # Materializing allows two passes: first to extract cohort IDs, then to
    # serialize — one DB round trip instead of two.
    all_flags = list(
        flag_queryset.exclude(ineligible)
        .annotate(
            evaluation_tag_names_agg=ArrayAgg(
                "flag_evaluation_contexts__evaluation_context__name",
                filter=Q(flag_evaluation_contexts__isnull=False),
                distinct=True,
            ),
            has_experiment_agg=live_experiment_exists(),
        )
        .order_by("team_id", "key")
    )

    direct_cohort_ids: set[int] = set()
    eligible_flags: list[FeatureFlag] = []
    dependency_references: set[str] = set()
    for flag in all_flags:
        if not _is_supported_legacy_flag(flag):
            excluded_by_team[flag.team_id][str(flag.pk)] = flag.key
            continue
        flag._evaluation_tag_names = flag.evaluation_tag_names_agg or []
        flag._has_experiment = flag.has_experiment_agg
        direct_cohort_ids.update(referenced_cohort_ids(flag.filters))
        dependency_references.update(str(prop["key"]) for prop in flag_dependency_properties(flag.filters))
        eligible_flags.append(flag)

    if dependency_references:
        dependency_ids = {
            flag_id for reference in dependency_references if (flag_id := safe_int(reference)) is not None
        }
        # Ineligible targets still exclude dependents when their format is unsupported.
        # They need no model instances, evaluation contexts, or experiment annotations.
        for flag_id, key, team_id, filters in (
            flag_queryset.filter(ineligible)
            .filter(Q(pk__in=dependency_ids) | Q(key__in=dependency_references))
            .values_list("id", "key", "team_id", "filters")
        ):
            try:
                validate_legacy_filters(filters)
            except (ConfigFormatError, TypeError, ValueError):
                excluded_by_team[team_id][str(flag_id)] = key

    # Load only the referenced cohorts and resolve nested dependencies
    # iteratively. Each iteration loads newly discovered nested cohort IDs
    # until there are none left (typically 1-2 iterations).
    cohorts_by_project: dict[int, dict[int, Cohort]] = defaultdict(dict)
    ids_to_load = direct_cohort_ids.copy()
    loaded_ids: set[int] = set()

    malformed_cohort_ids: set[int] = set()
    cohort_definitions: dict[int, _LegacyCohortDefinition] = {}
    while ids_to_load:
        newly_loaded: list[Cohort] = []
        cohort_qs = (
            # nosemgrep: idor-lookup-without-team — team scope is enforced via team__project_id__in.
            Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
            .filter(pk__in=ids_to_load, team__project_id__in=project_ids, deleted=False, is_static=False)
            .select_related("team")
        )
        for cohort in cohort_qs:
            cohorts_by_project[cohort.team.project_id][cohort.pk] = cohort
            loaded_ids.add(cohort.pk)
            newly_loaded.append(cohort)

        # Mark all requested IDs as loaded (including missing ones) to avoid retrying
        loaded_ids.update(ids_to_load)

        # Extract nested cohort references from newly loaded cohorts
        nested_ids: set[int] = set()
        for cohort in newly_loaded:
            try:
                definition = _serialize_legacy_cohort(cohort)
                cohort_definitions[cohort.pk] = definition
                nested_ids.update(definition.dependencies)
            except _MALFORMED_DEFINITION_ERRORS:
                logger.warning(
                    "Malformed cohort omitted from legacy definitions",
                    extra={"team_id": cohort.team_id, "cohort_id": cohort.pk},
                    exc_info=True,
                )
                malformed_cohort_ids.add(cohort.pk)

        ids_to_load = nested_ids - loaded_ids

    # Bulk load group type mappings for all projects
    gtm_by_project: dict[int, dict[str, str]] = defaultdict(dict)
    for pid, mappings in get_group_types_for_projects(list(project_ids)).items():
        for m in mappings:
            gtm_by_project[pid][str(m["group_type_index"])] = m["group_type"]

    results: dict[int, dict[str, Any]] = {}
    failed_team_ids: set[int] = set()

    for tid, team_flags_iter in groupby(eligible_flags, key=lambda f: f.team_id):
        team = team_by_id.get(tid)
        if team is None:
            continue

        try:
            project_cohorts = cohorts_by_project.get(team.project_id, {})

            flags_data: list[dict[str, Any]] = []
            flag_cohort_ids: dict[str, set[int]] = {}
            flag_id_to_key: dict[str, str] = {}

            for feature_flag in team_flags_iter:
                try:
                    cohort_ids = _flag_cohort_ids(
                        feature_flag.get_filters(), project_cohorts, cohort_definitions, malformed_cohort_ids
                    )
                    flags_data.append(EvaluationFeatureFlagSerializer(feature_flag, context={}).data)
                except _MALFORMED_DEFINITION_ERRORS:
                    excluded_by_team[tid][str(feature_flag.pk)] = feature_flag.key
                    logger.warning(
                        "Malformed feature flag omitted from legacy definitions",
                        extra={"team_id": tid, "flag_id": feature_flag.pk},
                        exc_info=True,
                    )
                    FLAG_PROCESSING_ERROR_COUNTER.inc()
                    continue
                flag_cohort_ids[feature_flag.key] = cohort_ids
                flag_id_to_key[str(feature_flag.id)] = feature_flag.key

            flags_data = drop_legacy_dependents(flags_data, excluded_by_team[tid])
            minimal_flag_called_events, property_matching_version = team_config_by_team_id.get(
                tid, (False, PropertyMatchingVersion.LEGACY)
            )
            response_data = _local_eval_response(
                flags=flags_data,
                group_type_mapping=gtm_by_project.get(team.project_id, {}),
                cohorts={
                    str(cohort_id): cohort_definitions[cohort_id].properties
                    for flag in flags_data
                    for cohort_id in flag_cohort_ids[flag["key"]]
                },
                minimal_flag_called_events=minimal_flag_called_events,
                property_matching_version=property_matching_version,
            )
            results[tid] = _apply_flag_dependency_transformation(response_data, flag_id_to_key)
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            logger.exception("Flag definitions build failed for team", team_id=tid)
            failed_team_ids.add(tid)

    # Ensure every requested team has a result, even if it had no flags
    for tid in team_ids:
        if tid not in results and tid not in failed_team_ids:
            minimal_flag_called_events, property_matching_version = team_config_by_team_id.get(
                tid, (False, PropertyMatchingVersion.LEGACY)
            )
            results[tid] = _local_eval_response(
                flags=[],
                group_type_mapping=gtm_by_project.get(team_by_id[tid].project_id, {}),
                cohorts={},
                minimal_flag_called_events=minimal_flag_called_events,
                property_matching_version=property_matching_version,
            )

    return results


def _update_flag_definitions(team: Team | int, ttl: int | None = None) -> bool:
    resolved_team = _resolve_team(team)
    if resolved_team is None:
        return False
    return flag_definitions_hypercache.update_cache(
        resolved_team, ttl=ttl, should_skip_write=_skip_write_if_group_mapping_emptied
    )


# HyperCache management config for warming/verification. Uses the same team-scoping
# queryset as flags_cache, giving flag definitions the same ~89% team reduction that
# the flags cache already has.
# The refresh builds flag definitions from team id/project_id; it reads no other Team
# columns. Narrowing the SELECT keeps it resilient to newly added Team columns the read
# replica may not have applied yet (organization_id keeps the select_related valid).
_FLAG_DEFINITIONS_REFRESH_ONLY_FIELDS = ["id", "project_id", "organization_id"]

FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=flag_definitions_hypercache,
    update_fn=_update_flag_definitions,
    cache_name="flag_definitions",
    get_teams_queryset_fn=get_teams_with_flags_queryset,
    get_team_ids_to_skip_fix_fn=get_team_ids_with_recently_updated_flags,
    # The Rust /flags/definitions reader has no DB fallback, so a miss must be
    # repaired even during the grace period rather than 503 until the next sweep.
    repair_miss_during_grace_period=True,
    # Guard the verifier's direct db_data write against caching an emptied
    # group_type_mapping (personhog lag), same as the signal-driven write path.
    should_skip_write=_skip_write_if_group_mapping_emptied,
    refresh_only_fields=_FLAG_DEFINITIONS_REFRESH_ONLY_FIELDS,
    # This cache is built in bulk, so its entries come due in bulk. The cost of dispersing
    # them is that each entry is refreshed more often than a flat TTL would refresh it.
    refresh_ttl_min_fraction=0.7,
)


# Top-level blob fields (besides "flags", compared separately by key) checked for drift by
# verify_team_flag_definitions. Each entry is (field, mismatch type, default used when a legacy
# blob predates the field — None means the field has always been present).
_TOP_LEVEL_FIELDS_TO_COMPARE: list[tuple[str, str, Any]] = [
    ("cohorts", "COHORTS_MISMATCH", None),
    ("group_type_mapping", "GROUP_TYPE_MAPPING_MISMATCH", None),
    ("minimal_flag_called_events", "MINIMAL_FLAG_CALLED_EVENTS_MISMATCH", False),
    ("property_matching_version", "PROPERTY_MATCHING_VERSION_MISMATCH", PropertyMatchingVersion.LEGACY),
]


def verify_team_flag_definitions(
    team: Team,
    db_batch_data: dict | None = None,
    cache_batch_data: dict | None = None,
    verbose: bool = False,
) -> dict:
    """
    Verify a team's flag definitions cache against the database.

    Args:
        team: Team to verify
        db_batch_data: Pre-loaded DB data from batch_load_fn (keyed by team.id)
        cache_batch_data: Pre-loaded cache data from batch_get_from_cache (keyed by team.id)
        verbose: If True, include detailed diffs

    Returns:
        Dict with 'status' ("match", "miss", "mismatch") and 'issue' type.
    """
    # Get cached data - use pre-loaded batch data if available.
    # The third tuple element (etag) is unused for flag-definitions verification.
    if cache_batch_data and team.id in cache_batch_data:
        cached_data, source, _ = cache_batch_data[team.id]
    else:
        cached_data, source = flag_definitions_hypercache.get_from_cache_with_source(team)

    # Get flag definitions from database
    if db_batch_data and team.id in db_batch_data:
        db_data = db_batch_data[team.id]
    else:
        db_data = _get_flags_response_for_local_evaluation(team)

    db_flags = db_data.get("flags", []) if isinstance(db_data, dict) else []

    # Cache miss — no usable cache entry (db/miss, or dependency_unavailable when a
    # cold load could not reach its upstream). All mean "nothing cached", not drift.
    if source in ("db", "miss", "dependency_unavailable"):
        return {
            "status": "miss",
            "issue": "CACHE_MISS",
            "details": f"No cache entry found (team has {len(db_flags)} flags in DB)",
            "db_data": db_data,
        }

    # Extract cached flags
    cached_flags = cached_data.get("flags", []) if cached_data else []

    # Compare flags by key (flag definitions use key as primary identifier)
    db_flags_by_key = {flag["key"]: flag for flag in db_flags}
    cached_flags_by_key = {flag["key"]: flag for flag in cached_flags}

    diffs = []

    # Find missing flags (in DB but not in cache)
    for flag_key in db_flags_by_key:
        if flag_key not in cached_flags_by_key:
            diffs.append(
                {
                    "type": "MISSING_IN_CACHE",
                    "flag_key": flag_key,
                }
            )

    # Find stale flags (in cache but not in DB)
    for flag_key in cached_flags_by_key:
        if flag_key not in db_flags_by_key:
            diffs.append(
                {
                    "type": "STALE_IN_CACHE",
                    "flag_key": flag_key,
                }
            )

    # Compare field values for flags that exist in both
    for flag_key in db_flags_by_key:
        if flag_key in cached_flags_by_key:
            db_flag = db_flags_by_key[flag_key]
            cached_flag = cached_flags_by_key[flag_key]
            field_diffs = _compare_flag_fields(db_flag, cached_flag)
            if field_diffs:
                diff: dict = {
                    "type": "FIELD_MISMATCH",
                    "flag_key": flag_key,
                    "diff_fields": [f["field"] for f in field_diffs],
                }
                if verbose:
                    diff["field_diffs"] = field_diffs
                diffs.append(diff)

    # Also compare top-level blob fields other than flags (cohorts, group_type_mapping, …).
    # A default other than None means a legacy blob missing the key isn't reported as drift.
    if cached_data is not None and db_data is not None:
        for field, mismatch_type, default in _TOP_LEVEL_FIELDS_TO_COMPARE:
            if cached_data.get(field, default) != db_data.get(field, default):
                diffs.append({"type": mismatch_type, "flag_key": field})

    if not diffs:
        return {"status": "match", "issue": "", "details": ""}

    # Summarize diffs
    missing_count = sum(1 for d in diffs if d.get("type") == "MISSING_IN_CACHE")
    stale_count = sum(1 for d in diffs if d.get("type") == "STALE_IN_CACHE")
    mismatch_count = sum(1 for d in diffs if d.get("type") == "FIELD_MISMATCH")
    mismatched_types = {d.get("type") for d in diffs}

    summary_parts = []
    if missing_count > 0:
        summary_parts.append(f"{missing_count} missing")
    if stale_count > 0:
        summary_parts.append(f"{stale_count} stale")
    if mismatch_count > 0:
        summary_parts.append(f"{mismatch_count} mismatched")

    flag_summary = f"{', '.join(summary_parts)} flags" if summary_parts else ""
    extra_parts = [
        f"{field} mismatch"
        for field, mismatch_type, _ in _TOP_LEVEL_FIELDS_TO_COMPARE
        if mismatch_type in mismatched_types
    ]

    details = "; ".join(filter(None, [flag_summary, ", ".join(extra_parts)]))

    result: dict = {
        "status": "mismatch",
        "issue": "DATA_MISMATCH",
        "details": details or "unknown differences",
        "db_data": db_data,
    }

    if verbose:
        result["diffs"] = diffs

    return result


# NOTE: All models that affect feature flag evaluation should have a signal to update the cache
# GroupTypeMapping excluded as it's primarily managed by Node.js plugin-server


@receiver(post_save, sender=FeatureFlag)
@receiver(post_delete, sender=FeatureFlag)
def feature_flag_changed(sender, instance: "FeatureFlag", **kwargs):
    from products.feature_flags.backend.tasks import update_team_flags_cache

    # Defer task execution until after the transaction commits
    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=Experiment)
@receiver(post_delete, sender=Experiment)
def experiment_changed(sender, instance: "Experiment", **kwargs):
    # A flag's local-eval `has_experiment` depends on whether it has any non-deleted
    # linked experiment, so experiment changes must refresh the linked flag's team cache.
    # Fires on every save by design, mirroring feature_flag_changed: Experiment rows are
    # only written on user-driven lifecycle/edit operations (no high-churn periodic path
    # touches them), so an update_fields gate isn't warranted here.
    from products.feature_flags.backend.tasks import update_team_flags_cache

    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=Cohort)
@receiver(post_delete, sender=Cohort)
def cohort_changed(sender, instance: "Cohort", **kwargs):
    if is_cohort_recalculation_only_save(kwargs):
        return

    from products.feature_flags.backend.tasks import update_team_flags_cache

    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=FeatureFlagEvaluationContext)
@receiver(post_delete, sender=FeatureFlagEvaluationContext)
def evaluation_context_changed(sender, instance: "FeatureFlagEvaluationContext", **kwargs):
    from products.feature_flags.backend.tasks import update_team_flags_cache

    team_id = instance.feature_flag.team_id
    transaction.on_commit(lambda: update_team_flags_cache.delay(team_id))


@receiver(post_save, sender=EvaluationContext)
def evaluation_context_name_changed(sender, instance: "EvaluationContext", created: bool, **kwargs):
    """Invalidate cache when an EvaluationContext's name changes, so flags
    referencing it pick up the new name on the next evaluation."""
    if created:
        return  # New contexts can't be referenced by any flags yet

    from products.feature_flags.backend.tasks import update_team_flags_cache

    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))
