import json
import datetime as dt

import redis
import structlog
from structlog.stdlib import BoundLogger
from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.growth.backend.constants import TEAM_SDK_CACHE_EXPIRY, SdkVersionEntry, team_sdk_versions_v3_key
from products.growth.backend.sdk_version_rollup import SDK_VERSIONS_WINDOW_DAYS, merge_live_usage, sdk_versions_window

default_logger: BoundLogger = structlog.get_logger(__name__)

# HogQL returns 100 rows unless the query sets a LIMIT. A team can have more SDK versions than that.
QUERY = parse_select("""
    SELECT
        properties.$lib AS lib,
        properties.$lib_version AS lib_version,
        MAX(timestamp) AS max_timestamp,
        COUNT(*) AS event_count
    FROM events
    WHERE
        timestamp >= {since}
        AND lib IS NOT NULL
        AND (lib = 'posthog-java' OR (lib_version IS NOT NULL AND lib_version != ''))
    GROUP BY lib, lib_version
    ORDER BY event_count DESC
    LIMIT 10000
""")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def run_query(team: Team, since: dt.datetime) -> HogQLQueryResponse:
    query_type = "sdk_versions_for_team"
    with tags_context(
        product=Product.SDK_HEALTH,
        feature=Feature.HEALTH_CHECK,
        team_id=team.pk,
        org_id=team.organization_id,
        query_type=query_type,
    ):
        response = execute_hogql_query(
            QUERY,
            team,
            query_type=query_type,
            placeholders={"since": ast.Constant(value=since)},
            workload=Workload.ONLINE,
        )
    return response


def get_sdk_versions_for_team(
    team_id: int,
    *,
    logger: BoundLogger = default_logger,
) -> dict[str, list[SdkVersionEntry]] | None:
    """
    SDK usage for the last week, grouped by lib type.

    Reads the daily rollup plus a live query for the hours since it ended. When the rollup has no
    fresh window, falls back to a 7-day query over raw events.
    """
    try:
        team = Team.objects.get(id=team_id)
        window = sdk_versions_window()
        if window is None:
            logger.info("sdk_health_rollup_unavailable", team_id=team_id)
            since = dt.datetime.now(dt.UTC) - dt.timedelta(days=SDK_VERSIONS_WINDOW_DAYS)
        else:
            since = window.live_since
        live_rows = [tuple(row) for row in run_query(team, since).results]
        return merge_live_usage(team_id, window, live_rows)
    except Team.DoesNotExist:
        logger.exception(f"[SDK Health] Team {team_id} not found")
        return {}  # Safe to return empty dict, this is not an error
    except Exception as e:
        logger.exception(f"[SDK Health] Error querying events for team {team_id}")
        capture_exception(e, {"team_id": team_id})
        return None


def get_and_cache_team_sdk_versions(
    team_id: int,
    redis_client: redis.Redis,
    *,
    logger: BoundLogger = default_logger,
) -> dict[str, list[SdkVersionEntry]] | None:
    """
    Query ClickHouse for team SDK versions and cache the result.
    Used by the SDK Health API for on-demand cache-miss fallback.
    Returns the response data dict or None if failed.
    """
    try:
        sdk_versions = get_sdk_versions_for_team(team_id, logger=logger)
        if sdk_versions is not None:
            payload = json.dumps(sdk_versions)
            cache_key = team_sdk_versions_v3_key(team_id)
            redis_client.setex(cache_key, TEAM_SDK_CACHE_EXPIRY, payload)
            logger.info(f"[SDK Health] Team {team_id} SDK versions cached successfully")

            return sdk_versions
        else:
            logger.error(f"[SDK Health] No data received from ClickHouse for team {team_id}")
            return None
    except Exception as e:
        logger.exception(f"[SDK Health] Failed to get and cache SDK versions for team {team_id}")
        capture_exception(e)
        return None
