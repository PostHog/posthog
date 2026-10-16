import time
from datetime import datetime
from uuid import UUID

from django.core.cache import cache
from django.db import transaction

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.materialized_columns import get_materialized_column_for_property
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.constants import FlagRequestType
from posthog.exceptions_capture import capture_exception
from posthog.helpers.dashboard_templates import add_enriched_insights_to_feature_flag_dashboard
from posthog.models import Team
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_TABLE
from posthog.redis import get_client

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_flag_evaluations_read_mode
from products.feature_flags.backend.models.feature_flag import FeatureFlag

REDIS_LOCK_TOKEN = "posthog:decide_analytics:lock"
CACHE_BUCKET_SIZE = 60 * 2  # duration in seconds

# SDK library names must match the Rust Library::as_str() values in
# rust/feature-flags/src/handler/types.rs
SDK_LIBRARIES = [
    "posthog-js",
    "posthog-node",
    "posthog-node-mcp",
    "posthog-edge",
    "posthog-convex",
    "posthog-python",
    "posthog-python-mcp",
    "posthog-php",
    "posthog-ruby",
    "posthog-rails",
    "posthog-go",
    "posthog-java",
    "posthog-dotnet",
    "posthog-aspnetcore",
    "posthog-elixir",
    "posthog-rs",
    "posthog-android",
    "posthog-ios",
    "posthog-react-native",
    "posthog-flutter",
    "posthog-kmp",
    "posthog-unity",
    "posthog-server",
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
                # A failed enrichment rolls back the flag update, so the next run retries this
                # flag instead of skipping it as already enriched.
                with transaction.atomic():
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


def _build_cross_project_evals_query(from_flag_evaluations: bool) -> str:
    if from_flag_evaluations:
        # flag_evaluations stores only $feature_flag_called rows, so it needs no event filter.
        table, prewhere, flag_key_filter = FLAG_EVALUATIONS_TABLE, "", "flag_key = %(flag_key)s"
    else:
        table, prewhere, flag_key_filter = "events", "PREWHERE event = '$feature_flag_called'", _flag_key_filter_sql()
    return f"""
SELECT team_id, count() AS evaluations
FROM {table}
{prewhere}
WHERE {flag_key_filter}
  AND team_id IN %(team_ids)s
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY team_id
"""


def get_evaluations_7d_by_team(
    flag_key: str, team_ids: list[int], *, from_flag_evaluations: bool
) -> dict[int, int] | None:
    """Return per-team 7-day counts of `$feature_flag_called` events for flag_key.

    Reads flag_evaluations when `from_flag_evaluations` is set, and events otherwise.
    Returns a dict mapping team_id -> count (all requested team ids are present;
    teams with no events map to 0). Returns `None` when ClickHouse fails so the
    caller can render an unavailable state instead of a misleading zero.
    """
    if not team_ids:
        return {}

    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY, name="get_evaluations_7d_by_team")
    try:
        rows = sync_execute(
            _build_cross_project_evals_query(from_flag_evaluations),
            {"flag_key": flag_key, "team_ids": tuple(team_ids)},
        )
    except Exception as error:
        capture_exception(error)
        return None

    counts = dict.fromkeys(team_ids, 0)
    for team_id, evaluations in rows:
        counts[int(team_id)] = int(evaluations)
    return counts


def get_cached_evaluations_7d_by_team(
    flag_key: str, team_ids: list[int], organization_id: UUID
) -> dict[int, int] | None:
    """Cached variant of get_evaluations_7d_by_team with a 5-minute TTL.

    Every team in `team_ids` must belong to the organization `organization_id`.
    Failure results (None) are not cached, so recovery is immediate once
    ClickHouse is reachable again.
    """
    if not team_ids:
        return {}

    from_flag_evaluations = get_flag_evaluations_read_mode(organization_id) != FlagEvaluationsMode.EVENTS
    # The key names the source table, so a mode change cannot serve a count read from the other table.
    source = FLAG_EVALUATIONS_TABLE if from_flag_evaluations else "events"
    cache_key = f"flag_analytics:evals_7d:{source}:{flag_key}:" + ",".join(str(t) for t in sorted(team_ids))
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = get_evaluations_7d_by_team(flag_key, team_ids, from_flag_evaluations=from_flag_evaluations)
    if result is not None:
        cache.set(cache_key, result, timeout=CROSS_PROJECT_EVALS_CACHE_TTL)
    return result
