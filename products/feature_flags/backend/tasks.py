import time

from django.conf import settings
from django.core.cache import cache as django_cache
from django.db.models import Count, F, Func, IntegerField, Max, Sum, TextField
from django.db.models.functions import Cast

import structlog
from celery import shared_task
from prometheus_client import Gauge

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.api.capture import capture_batch_internal
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.utils import CeleryQueue, PushGatewayTask

from products.feature_flags.backend.canary import run_local_eval_canary
from products.feature_flags.backend.cross_region_flag_sync import sync_cross_region_flags
from products.feature_flags.backend.flags_cache import (
    cleanup_stale_expiry_tracking,
    clear_flags_cache,
    get_cache_stats,
    publish_shadow_invalidation,
    refresh_expiring_flags_caches,
    update_flags_cache,
)
from products.feature_flags.backend.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    clear_flag_definition_caches,
    update_flag_caches,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.rebuild_queue import drain_rebuild_requests

logger = structlog.get_logger(__name__)

# Matches the task's hard time_limit so a crashed run's lock expires before the next
# 5-minute schedule.
LOCAL_EVAL_CANARY_LOCK_TIMEOUT_SECONDS = 90

ENROLLMENT_MIGRATION_PAGE_SIZE = MAX_SELECT_RETURNED_ROWS


@shared_task(ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS.value)
@skip_team_scope_audit
def update_team_flags_cache(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    update_flag_caches(team)


# Bounded below the 1-minute schedule so a slow drain (e.g. a large post-eviction
# backlog rebuilt inline) can't run past the next tick and pin a worker. Teams not
# reached before the limit stay missing and are re-enqueued by their next miss.
@shared_task(
    ignore_result=True,
    queue=CeleryQueue.FEATURE_FLAGS.value,
    soft_time_limit=50,
    time_limit=55,
)
def drain_flag_definitions_rebuild_requests() -> None:
    """Drain the flag-definitions self-heal queue, rebuilding caches the Rust
    /flags/definitions endpoint reported missing. Scheduled every minute."""
    drain_rebuild_requests()


@shared_task(ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def sync_cross_region_flags_task() -> None:
    """Celery entrypoint for sync_cross_region_flags.

    On its own queue (not CeleryQueue.FEATURE_FLAGS) because it makes a blocking
    cross-region HTTP call: a stalled upstream shouldn't be able to delay the
    fast, sub-second signal-driven cache rebuilds sharing that queue.
    """
    sync_cross_region_flags()


# Pinned: products.cohorts dispatches this by name (a static import would close a product-dependency
# cycle), so a module move must not silently rename the registration out from under that caller.
@shared_task(
    name="products.feature_flags.backend.tasks.update_team_service_flags_cache",
    ignore_result=True,
    queue=CeleryQueue.FEATURE_FLAGS.value,
)
@skip_team_scope_audit
def update_team_service_flags_cache(team_id: int) -> None:
    """
    Update the service flags cache for a specific team.

    This task is triggered when feature flags change or when teams are created,
    ensuring the feature-flags service has fresh data in HyperCache.
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.debug("Team does not exist for service flags cache update", team_id=team_id)
        HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
            namespace="feature_flags", cache_name="flags", operation="update", result="failure"
        ).inc()
        return

    success = update_flags_cache(team)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="feature_flags", cache_name="flags", operation="update", result="success" if success else "failure"
    ).inc()

    # KAFKA-CUTOVER TRANSITIONAL CODE — remove with the block it belongs to in
    # flags_cache.py. Gated on `success` because a shadow build must diff against
    # the entry this task just wrote. After a failed write the live entry is the
    # stale one, and the diff would report Python's failure as Rust drift.
    if success:
        publish_shadow_invalidation(team_id)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
@skip_team_scope_audit
def migrate_feature_enrollment_on_key_change(team_id: int, old_key: str, flag_id: int) -> None:
    """
    Copy `$feature_enrollment/<old_key>` person properties to the flag's key after a rename,
    so existing early access opt-ins (and explicit opt-outs) keep applying — evaluation
    derives the enrollment property name from the flag's current key.

    The destination is the flag's key as of execution, not as of the rename, so a chain of
    renames converges on the final key instead of stranding people on an intermediate one.
    Writes use `$set_once`, so a person who makes a fresh choice under the new key during the
    migration can't be clobbered, and retries are harmless. The old property is kept so
    renaming back stays lossless. Enrollees are paged through by person id.
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist for enrollment migration", team_id=team_id)
        return

    flag = FeatureFlag.objects.filter(team_id=team_id, id=flag_id, deleted=False).first()
    if flag is None:
        return

    new_key = flag.key
    if new_key == old_key:
        return

    new_prop = f"$feature_enrollment/{new_key}"
    cursor = ""

    while True:
        # Property access (rather than JSONExtractString) lets the HogQL printer use
        # materialized person-property columns when available.
        response = execute_hogql_query(
            """
            SELECT
                toString(id) AS person_id,
                argMax(pdi.distinct_id, created_at) AS distinct_id,
                properties[{old_prop}] AS enrollment_value
            FROM persons
            WHERE properties[{old_prop}] IN ('true', 'false')
            AND properties[{new_prop}] IS NULL
            AND toString(id) > {cursor}
            GROUP BY id, enrollment_value
            ORDER BY person_id
            LIMIT {limit}
            """,
            placeholders={
                "old_prop": ast.Constant(value=f"$feature_enrollment/{old_key}"),
                "new_prop": ast.Constant(value=new_prop),
                "cursor": ast.Constant(value=cursor),
                "limit": ast.Constant(value=ENROLLMENT_MIGRATION_PAGE_SIZE),
            },
            team=team,
            limit_context=LimitContext.QUERY_ASYNC,
        )

        if not response.results:
            return

        # A person whose distinct ids all moved to another person in a merge joins to nothing
        # and comes back blank; capture rejects the whole batch over one such event.
        events = [
            {
                "event": "$set",
                "distinct_id": distinct_id,
                "properties": {"$set_once": {new_prop: enrollment_value == "true"}},
            }
            for _person_id, distinct_id, enrollment_value in response.results
            if distinct_id
        ]
        if events:
            capture_batch_internal(
                events=events,
                token=team.api_token,
                event_source="feature_flag_enrollment_key_migration",
                process_person_profile=True,
            ).raise_for_status()

        if len(response.results) < ENROLLMENT_MIGRATION_PAGE_SIZE:
            return

        cursor = response.results[-1][0]


@shared_task(ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS.value)
@skip_team_scope_audit
def clear_team_evaluation_cache(team_id: int) -> None:
    """Clear the /flags evaluation cache for a specific team, enqueued by staff tooling."""
    clear_flags_cache(team_id)


@shared_task(ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS.value)
@skip_team_scope_audit
def clear_team_definitions_cache(team_id: int) -> None:
    """Clear the /flags/definitions local-eval cache for a specific team, enqueued by staff tooling."""
    clear_flag_definition_caches(team_id)


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def refresh_expiring_flags_cache_entries(self: PushGatewayTask) -> None:
    """
    Periodic task to refresh flags caches before they expire.

    This task runs hourly and refreshes caches with TTL < 24 hours to prevent cache misses.

    Note: Most cache updates happen via Django signals when flags change.
    This job just prevents expiration-related cache misses.

    For initial cache build or schema migrations, use the management command:
        python manage.py warm_flags_cache
    """

    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping flags cache refresh")
        return

    # Create metrics gauges for this task run
    successful_gauge = Gauge(
        "posthog_flags_cache_refresh_successful_count",
        "Number of flags caches successfully refreshed",
        registry=self.metrics_registry,
    )
    failed_gauge = Gauge(
        "posthog_flags_cache_refresh_failed_count",
        "Number of flags caches that failed to refresh",
        registry=self.metrics_registry,
    )

    start_time = time.time()
    logger.info(
        "Starting flags cache sync",
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    counts = refresh_expiring_flags_caches(
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    # Record metrics
    successful_gauge.set(counts.successful)
    failed_gauge.set(counts.failed)

    # Note: Teams processed metrics are pushed to Pushgateway by
    # cache_expiry_manager.refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

    # Scan after refresh for metrics (pushes to Pushgateway via get_cache_stats)
    stats_after = get_cache_stats()

    duration = time.time() - start_time

    logger.info(
        "Completed flags cache refresh",
        successful_refreshes=counts.successful,
        failed_refreshes=counts.failed,
        total_cached=stats_after.get("total_cached", 0),
        total_teams=stats_after.get("total_teams", 0),
        cache_coverage=stats_after.get("cache_coverage", "unknown"),
        ttl_distribution=stats_after.get("ttl_distribution", {}),
        duration_seconds=duration,
    )


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def cleanup_stale_flags_expiry_tracking_task(self: PushGatewayTask) -> None:
    """
    Periodic task to clean up stale entries in the flags cache expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Runs daily to prevent sorted set bloat from deleted teams.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping flags expiry tracking cleanup")
        return

    entries_cleaned_gauge = Gauge(
        "posthog_cleanup_stale_flags_expiry_entries_cleaned",
        "Number of stale expiry tracking entries cleaned up",
        registry=self.metrics_registry,
    )

    removed_count = cleanup_stale_expiry_tracking()
    entries_cleaned_gauge.set(removed_count)
    logger.info("Completed flags expiry tracking cleanup", removed_count=removed_count)


def _set_ranked_team_gauge(gauge: Gauge, rows: list[dict], value_key: str) -> None:
    """Set gauge values for a ranked list of team metrics."""
    for rank, row in enumerate(rows, start=1):
        gauge.labels(
            rank=str(rank),
            team_id=str(row["team_id"]),
            team_name=row["team__name"] or "Unknown",
        ).set(row[value_key] or 0)


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
@skip_team_scope_audit
def compute_feature_flag_metrics(self: PushGatewayTask) -> None:
    """
    Compute and push feature flag metrics for Grafana dashboards.

    Metrics:
    - posthog_feature_flag_team_flag_count: Top 5 teams by active flag count
    - posthog_feature_flag_team_largest_flag_bytes: OCTET_LENGTH for top 5 teams (ranked by pg_column_size)
    - posthog_feature_flag_team_largest_flag_pg_bytes: pg_column_size for top 5 teams
    - posthog_feature_flag_team_total_size_bytes: OCTET_LENGTH for top 5 teams (ranked by pg_column_size)
    - posthog_feature_flag_team_total_size_pg_bytes: pg_column_size for top 5 teams

    Uses a two-phase query approach for size metrics:
    - Phase 1: Fast ranking with pg_column_size to select and rank the top 5 teams
    - Phase 2: Compute both OCTET_LENGTH and pg_column_size for those teams

    Both metrics use pg_column_size ranking for consistency. Reports both values because:
    - pg_column_size: PostgreSQL storage footprint (TOAST-compressed)
    - OCTET_LENGTH: Text representation size of the filters field
    """
    if not settings.PROM_PUSHGATEWAY_ADDRESS:
        logger.debug("Pushgateway not configured, skipping feature flag metrics computation")
        return

    flag_count_gauge = Gauge(
        "posthog_feature_flag_team_flag_count",
        "Number of active feature flags per team (top 5)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    largest_flag_gauge = Gauge(
        "posthog_feature_flag_team_largest_flag_bytes",
        "Text representation size of the largest feature flag filter per team (top 5)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    largest_flag_pg_gauge = Gauge(
        "posthog_feature_flag_team_largest_flag_pg_bytes",
        "PostgreSQL storage size of the largest feature flag filter per team (top 5, pg_column_size)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    total_size_gauge = Gauge(
        "posthog_feature_flag_team_total_size_bytes",
        "Total text representation size of all feature flag filters per team (top 5)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    total_size_pg_gauge = Gauge(
        "posthog_feature_flag_team_total_size_pg_bytes",
        "PostgreSQL total storage size of all feature flag filters per team (top 5, pg_column_size)",
        labelnames=["rank", "team_id", "team_name"],
        registry=self.metrics_registry,
    )

    base_qs = FeatureFlag.objects.filter(active=True)

    # Top 5 by flag count (secondary sort by team_id for deterministic ordering on ties)
    top_by_count = list(
        base_qs.values("team_id", "team__name").annotate(flag_count=Count("id")).order_by("-flag_count", "team_id")[:5]
    )

    # Size expressions
    pg_size = Func(F("filters"), function="pg_column_size", output_field=IntegerField())
    octet_size = Func(Cast(F("filters"), TextField()), function="OCTET_LENGTH", output_field=IntegerField())

    # Phase 1: Fast ranking with pg_column_size for "largest flag" metric
    top_largest_ranking = list(
        base_qs.annotate(pg_size=pg_size)
        .values("team_id")
        .annotate(max_pg_size=Max("pg_size"))
        .order_by("-max_pg_size", "team_id")[:5]
    )
    top_largest_team_ids = [t["team_id"] for t in top_largest_ranking]

    # Phase 2: Compute both metrics for top 5 teams, ordered by pg_column_size (Phase 1 ranking)
    top_by_largest = list(
        base_qs.filter(team_id__in=top_largest_team_ids)
        .annotate(filters_size=octet_size, pg_size=pg_size)
        .values("team_id", "team__name")
        .annotate(largest_flag_size=Max("filters_size"), largest_flag_pg_size=Max("pg_size"))
        .order_by("-largest_flag_pg_size", "team_id")
    )

    # Phase 1: Fast ranking with pg_column_size for "total size" metric
    top_total_ranking = list(
        base_qs.annotate(pg_size=pg_size)
        .values("team_id")
        .annotate(sum_pg_size=Sum("pg_size"))
        .order_by("-sum_pg_size", "team_id")[:5]
    )
    top_total_team_ids = [t["team_id"] for t in top_total_ranking]

    # Phase 2: Compute both metrics for top 5 teams, ordered by pg_column_size (Phase 1 ranking)
    top_by_total = list(
        base_qs.filter(team_id__in=top_total_team_ids)
        .annotate(filters_size=octet_size, pg_size=pg_size)
        .values("team_id", "team__name")
        .annotate(total_size=Sum("filters_size"), total_pg_size=Sum("pg_size"))
        .order_by("-total_pg_size", "team_id")
    )

    _set_ranked_team_gauge(flag_count_gauge, top_by_count, "flag_count")
    _set_ranked_team_gauge(largest_flag_gauge, top_by_largest, "largest_flag_size")
    _set_ranked_team_gauge(largest_flag_pg_gauge, top_by_largest, "largest_flag_pg_size")
    _set_ranked_team_gauge(total_size_gauge, top_by_total, "total_size")
    _set_ranked_team_gauge(total_size_pg_gauge, top_by_total, "total_pg_size")

    logger.info(
        "Computed feature flag metrics",
        top_flag_count=top_by_count[0]["flag_count"] if top_by_count else 0,
        top_largest_flag_bytes=top_by_largest[0]["largest_flag_size"] if top_by_largest else 0,
        top_largest_flag_pg_bytes=top_by_largest[0]["largest_flag_pg_size"] if top_by_largest else 0,
        top_total_size_bytes=top_by_total[0]["total_size"] if top_by_total else 0,
        top_total_size_pg_bytes=top_by_total[0]["total_pg_size"] if top_by_total else 0,
    )


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def refresh_expiring_flag_definitions_cache_entries(self: PushGatewayTask) -> None:
    """
    Periodic task to refresh the flag definitions cache before entries expire.

    Runs hourly and refreshes caches with TTL < 24 hours to prevent cache misses.

    Note: Most cache updates happen via Django signals when flags change.
    This job just prevents expiration-related cache misses.
    """

    from posthog.storage.cache_expiry_manager import refresh_expiring_caches

    successful_gauge = Gauge(
        "posthog_flag_definitions_cache_refresh_successful_count",
        "Number of flag definitions caches successfully refreshed",
        registry=self.metrics_registry,
    )
    failed_gauge = Gauge(
        "posthog_flag_definitions_cache_refresh_failed_count",
        "Number of flag definitions caches that failed to refresh",
        registry=self.metrics_registry,
    )

    start_time = time.time()
    logger.info(
        "Starting flag definitions cache sync",
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    counts = refresh_expiring_caches(
        config=FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    successful_gauge.set(counts.successful)
    failed_gauge.set(counts.failed)

    duration = time.time() - start_time
    logger.info(
        "Completed flag definitions cache refresh",
        successful_refreshes=counts.successful,
        failed_refreshes=counts.failed,
        duration_seconds=duration,
    )


@shared_task(bind=True, base=PushGatewayTask, ignore_result=True, queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value)
def cleanup_stale_flag_definitions_expiry_tracking_task(self: PushGatewayTask) -> None:
    """
    Periodic task to clean up stale entries in the flag definitions cache expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Runs daily to prevent sorted set bloat from deleted teams.
    """

    from posthog.storage.cache_expiry_manager import cleanup_stale_expiry_tracking

    entries_cleaned_gauge = Gauge(
        "posthog_cleanup_stale_flag_definitions_expiry_entries_cleaned",
        "Number of stale flag definitions expiry tracking entries cleaned up",
        registry=self.metrics_registry,
    )

    removed_count = cleanup_stale_expiry_tracking(FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG)

    entries_cleaned_gauge.set(removed_count)
    logger.info("Completed flag definitions expiry tracking cleanup", removed_count=removed_count)


@shared_task(
    bind=True,
    base=PushGatewayTask,
    ignore_result=True,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    soft_time_limit=60,
    time_limit=LOCAL_EVAL_CANARY_LOCK_TIMEOUT_SECONDS,
)
def feature_flags_local_eval_canary_task(self: PushGatewayTask) -> None:
    """Periodic canary for feature-flags local evaluation.

    Builds the configured team's local-eval payload and checks its group_type_mapping
    is non-empty. Does nothing unless FEATURE_FLAGS_CANARY_TEAM_ID is set. A
    distributed lock skips overlapping runs.

    Metrics:
    - posthog_feature_flags_local_eval_canary_group_mapping_present (gauge, 1/0)
    - posthog_feature_flags_local_eval_canary_failure_total (counter)
    """
    if settings.FEATURE_FLAGS_CANARY_TEAM_ID is None:
        return

    lock_key = "posthog:feature_flags_local_eval_canary:lock"
    if not django_cache.add(lock_key, "locked", timeout=LOCAL_EVAL_CANARY_LOCK_TIMEOUT_SECONDS):
        logger.info("Skipping feature flags local-eval canary - already running")
        return

    try:
        run_local_eval_canary(self.metrics_registry)
    finally:
        django_cache.delete(lock_key)
