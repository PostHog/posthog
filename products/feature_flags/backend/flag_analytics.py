import time
from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.materialized_columns import get_materialized_column_for_property
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.constants import FlagRequestType
from posthog.exceptions_capture import capture_exception
from posthog.helpers.dashboard_templates import add_enriched_insights_to_feature_flag_dashboard
from posthog.models import Team
from posthog.redis import get_client, redis

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.request_metrics import record_request_metrics

if TYPE_CHECKING:
    from posthoganalytics import Posthog

REDIS_LOCK_TOKEN = "posthog:decide_analytics:lock"
CACHE_BUCKET_SIZE = 60 * 2  # duration in seconds

# SDK library names must match the Rust Library::as_str() values in
# rust/feature-flags/src/handler/types.rs
SDK_LIBRARIES = [
    "posthog-js",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-java",
    "posthog-dotnet",
    "posthog-elixir",
    "posthog-rs",
    "posthog-android",
    "posthog-ios",
    "posthog-react-native",
    "posthog-flutter",
    "other",
]

# :NOTE: When making changes here, make sure you run test_no_interference_between_different_types_of_new_incoming_increments
# locally. It's not included in CI because of tricky patching freeze time in thread issues.


# Remote config requests are tracked for telemetry only; billing consumes just the decide and
# local evaluation events (see usage_report.py), so the remote config event never bills.
_REQUEST_BUCKET_PREFIXES = {
    FlagRequestType.DECIDE: "decide_requests",
    FlagRequestType.LOCAL_EVALUATION: "local_evaluation_requests",
    FlagRequestType.REMOTE_CONFIG: "remote_config_requests",
}

USAGE_EVENT_NAMES = {
    FlagRequestType.DECIDE: "decide usage",
    FlagRequestType.LOCAL_EVALUATION: "local evaluation usage",
    FlagRequestType.REMOTE_CONFIG: "remote config usage",
}


def _request_bucket_prefix(request_type: FlagRequestType) -> str:
    try:
        return _REQUEST_BUCKET_PREFIXES[request_type]
    except KeyError:
        raise ValueError(f"Unknown request type: {request_type}") from None


def get_team_request_key(team_id: int, request_type: FlagRequestType) -> str:
    return f"posthog:{_request_bucket_prefix(request_type)}:{team_id}"


def get_team_request_library_key(team_id: int, request_type: FlagRequestType, library: str) -> str:
    """Get the Redis key for SDK-specific request counts."""
    return f"posthog:{_request_bucket_prefix(request_type)}:sdk:{team_id}:{library}"


def increment_request_count(
    team_id: int, count: int = 1, request_type: FlagRequestType = FlagRequestType.DECIDE
) -> None:
    try:
        client = get_client()
        time_bucket = str(int(time.time() / CACHE_BUCKET_SIZE))
        key_name = get_team_request_key(team_id, request_type)
        client.hincrby(key_name, time_bucket, count)
    except Exception as error:
        capture_exception(error)


def _extract_counts_by_time_from_redis_hash(client: redis.Redis, key: str) -> dict[int, int]:
    """
    Consume every complete time bucket for `key`, returning counts keyed by the bucket's
    unix epoch second.

    Buckets are kept apart rather than summed here because `record_request_metrics` groups
    them into the hour they belong to.
    """
    counts_by_time: dict[int, int] = {}
    existing_values = client.hgetall(key)
    time_buckets = existing_values.keys()
    # The latest bucket is still being filled, so we don't want to delete it nor count it.
    # It will be counted in a later iteration, when it's not being filled anymore.
    if time_buckets and len(time_buckets) > 1:
        # redis returns encoded bytes, so we need to convert them into unix epoch for sorting
        for time_bucket in sorted(time_buckets, key=lambda bucket: int(bucket))[:-1]:
            counts_by_time[int(time_bucket) * CACHE_BUCKET_SIZE] = int(existing_values[time_bucket])
            client.hdel(key, time_bucket)

    return counts_by_time


def _totals_from_counts_by_time(counts_by_time: dict[int, int]) -> tuple[int, int, int]:
    """Reduce drained buckets to the (total, min_time, max_time) triple the billing event carries."""
    if not counts_by_time:
        return 0, int(time.time()), 0

    return sum(counts_by_time.values()), min(counts_by_time), max(counts_by_time)


def _sum_by_library(sdk_counts_by_time: dict[str, dict[int, int]]) -> dict[str, int]:
    return {library: sum(counts_by_time.values()) for library, counts_by_time in sdk_counts_by_time.items()}


def _extract_sdk_counts_by_time_from_redis(
    client: redis.Redis, team_id: int, request_type: FlagRequestType
) -> dict[str, dict[int, int]]:
    """
    Extract per-SDK request counts from Redis, consuming the buckets.
    Returns a dict mapping SDK name to counts keyed by the bucket's unix epoch second.

    Uses Redis pipelining to fetch all SDK keys in a single round-trip,
    then deletes consumed buckets in another round-trip.
    """
    # Build all keys upfront
    keys = [get_team_request_library_key(team_id, request_type, library) for library in SDK_LIBRARIES]

    # Pipeline HGETALL for all SDK keys in one round-trip
    pipe = client.pipeline(transaction=False)
    for key in keys:
        pipe.hgetall(key)
    results = pipe.execute()

    # Process results and collect buckets to delete
    sdk_counts_by_time: dict[str, dict[int, int]] = {}
    deletions: list[tuple[str, list[bytes]]] = []

    for library, key, existing_values in zip(SDK_LIBRARIES, keys, results):
        if not existing_values:
            continue

        time_buckets = existing_values.keys()
        # The latest bucket is still being filled, so we don't want to delete it nor count it.
        # It will be counted in a later iteration, when it's not being filled anymore.
        if len(time_buckets) <= 1:
            continue

        counts_by_time: dict[int, int] = {}
        buckets_to_delete: list[bytes] = []

        # Sort buckets and skip the latest one (still being filled)
        for time_bucket in sorted(time_buckets, key=lambda bucket: int(bucket))[:-1]:
            counts_by_time[int(time_bucket) * CACHE_BUCKET_SIZE] = int(existing_values[time_bucket])
            buckets_to_delete.append(time_bucket)

        if sum(counts_by_time.values()) > 0:
            sdk_counts_by_time[library] = counts_by_time
            deletions.append((key, buckets_to_delete))

    # Pipeline all deletions in one round-trip
    if deletions:
        pipe = client.pipeline(transaction=False)
        for key, buckets in deletions:
            for bucket in buckets:
                pipe.hdel(key, bucket)
        pipe.execute()

    return sdk_counts_by_time


def capture_usage_for_all_teams(ph_client: "Posthog") -> None:
    for team in Team.objects.exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True)).only("id", "uuid"):
        capture_team_decide_usage(ph_client, team.id, team.uuid)


def _capture_team_usage_for_request_type(
    ph_client: "Posthog",
    client: redis.Redis,
    team_id: int,
    team_uuid: str,
    request_type: FlagRequestType,
    billing_token: str | None,
) -> None:
    key_name = get_team_request_key(team_id, request_type)
    total_counts_by_time = _extract_counts_by_time_from_redis_hash(client, key_name)
    sdk_counts_by_time = _extract_sdk_counts_by_time_from_redis(client, team_id, request_type)
    total_count, min_time, max_time = _totals_from_counts_by_time(total_counts_by_time)

    # Recorded before the billing token check, so a self-hosted instance without a token still
    # gets the in-product breakdown.
    if total_count > 0:
        record_request_metrics(team_id, request_type, total_counts_by_time, sdk_counts_by_time)

    if total_count == 0 or not billing_token:
        return

    sdk_breakdown = _sum_by_library(sdk_counts_by_time)
    properties: dict = {
        "count": total_count,
        "team_id": team_id,
        "team_uuid": team_uuid,
        "min_time": min_time,
        "max_time": max_time,
        "token": billing_token,
    }
    if sdk_breakdown:
        properties["sdk_breakdown"] = sdk_breakdown

    ph_client.capture(
        distinct_id=team_id,
        event=USAGE_EVENT_NAMES[request_type],
        properties=properties,
    )


def capture_team_decide_usage(ph_client: "Posthog", team_id: int, team_uuid: str) -> None:
    try:
        client = get_client()

        with client.lock(f"{REDIS_LOCK_TOKEN}:{team_id}", timeout=60, blocking=False):
            billing_token = settings.DECIDE_BILLING_ANALYTICS_TOKEN
            for request_type in (
                FlagRequestType.DECIDE,
                FlagRequestType.LOCAL_EVALUATION,
                FlagRequestType.REMOTE_CONFIG,
            ):
                _capture_team_usage_for_request_type(ph_client, client, team_id, team_uuid, request_type, billing_token)

    except redis.exceptions.LockError:
        # lock wasn't acquired, which means another worker is working on this, so we don't need to do anything
        pass
    except Exception as error:
        capture_exception(error)


def _enriched_flag_key_expr_sql() -> str:
    """SQL expression for the `feature_flag` property, using the materialized column when available.

    This query spans all teams so it can't go through the HogQL printer; the
    materialized-column lookup has to be done by hand, with a JSONExtractString
    fallback for instances where the property isn't materialized. Nullable
    columns are coalesced to '' to match JSONExtractString's missing-property
    behavior.
    """
    column = get_materialized_column_for_property("events", "properties", "feature_flag")
    if column is None:
        return "JSONExtractString(properties, 'feature_flag')"
    if column.is_nullable:
        return f"ifNull(`{column.name}`, '')"
    return f"`{column.name}`"


def _build_enriched_analytics_query() -> str:
    return f"""
        SELECT team_id, {_enriched_flag_key_expr_sql()} as flag_key
        FROM events
        PREWHERE event IN ('$feature_view', '$feature_interaction')
        AND timestamp between %(begin)s AND %(end)s
        GROUP BY team_id, flag_key
    """


def find_flags_with_enriched_analytics(begin: datetime, end: datetime):
    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.ENRICHMENT, name="find_flags_with_enriched_analytics")
    result = sync_execute(_build_enriched_analytics_query(), {"begin": begin, "end": end})

    for row in result:
        team_id = row[0]
        flag_key = row[1]
        team = Team.objects.only("project_id").get(id=team_id)

        try:
            flag = FeatureFlag.objects.get(team__project_id=team.project_id, key=flag_key)
            if not flag.has_enriched_analytics:
                flag.has_enriched_analytics = True
                flag.save()
                if flag.usage_dashboard and not flag.usage_dashboard_has_enriched_insights:
                    add_enriched_insights_to_feature_flag_dashboard(flag, flag.usage_dashboard)
        except FeatureFlag.DoesNotExist:
            pass
        except Exception as e:
            capture_exception(e)


# Cross-project evaluation counts (used by the organization feature-flag projects grid)

CROSS_PROJECT_EVALS_CACHE_TTL = 300


def _flag_key_filter_sql() -> str:
    """SQL for matching the `$feature_flag` property, using the materialized column when available.

    Falls back to JSONExtractString so the query still works when the property
    isn't materialized on this ClickHouse instance.
    """
    column = get_materialized_column_for_property("events", "properties", "$feature_flag")
    if column is not None:
        # No ifNull for nullable columns: NULL never equals a real flag key,
        # matching the JSONExtractString('') behavior, and the bare column
        # keeps any skip index usable.
        return f"`{column.name}` = %(flag_key)s"
    return "JSONExtractString(properties, '$feature_flag') = %(flag_key)s"


def _build_cross_project_evals_query() -> str:
    return f"""
SELECT team_id, count() AS evaluations
FROM events
PREWHERE event = '$feature_flag_called'
WHERE {_flag_key_filter_sql()}
  AND team_id IN %(team_ids)s
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY team_id
"""


def get_evaluations_7d_by_team(flag_key: str, team_ids: list[int]) -> dict[int, int] | None:
    """Return per-team 7-day counts of `$feature_flag_called` events for flag_key.

    Returns a dict mapping team_id -> count (all requested team ids are present;
    teams with no events map to 0). Returns `None` when ClickHouse fails so the
    caller can render an unavailable state instead of a misleading zero.
    """
    if not team_ids:
        return {}

    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY, name="get_evaluations_7d_by_team")
    try:
        rows = sync_execute(_build_cross_project_evals_query(), {"flag_key": flag_key, "team_ids": tuple(team_ids)})
    except Exception as error:
        capture_exception(error)
        return None

    counts = dict.fromkeys(team_ids, 0)
    for team_id, evaluations in rows:
        counts[int(team_id)] = int(evaluations)
    return counts


def get_cached_evaluations_7d_by_team(flag_key: str, team_ids: list[int]) -> dict[int, int] | None:
    """Cached variant of get_evaluations_7d_by_team with a 5-minute TTL.

    Failure results (None) are not cached, so recovery is immediate once
    ClickHouse is reachable again.
    """
    if not team_ids:
        return {}

    cache_key = f"flag_analytics:evals_7d:{flag_key}:" + ",".join(str(t) for t in sorted(team_ids))
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = get_evaluations_7d_by_team(flag_key, team_ids)
    if result is not None:
        cache.set(cache_key, result, timeout=CROSS_PROJECT_EVALS_CACHE_TTL)
    return result
