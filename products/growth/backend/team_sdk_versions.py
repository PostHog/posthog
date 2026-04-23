import json
from collections import defaultdict

import redis
import structlog
from structlog.stdlib import BoundLogger
from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.schema import HogQLQueryResponse

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.growth.backend.constants import SDK_CACHE_EXPIRY, SdkVersionEntry, team_sdk_versions_key
from products.growth.dags.github_sdk_versions import SDK_TYPES

default_logger: BoundLogger = structlog.get_logger(__name__)

QUERY = parse_select("""
    SELECT
        properties.$lib AS lib,
        properties.$lib_version AS lib_version,
        MAX(timestamp) AS max_timestamp,
        COUNT(*) AS event_count
    FROM events
    WHERE
        timestamp >= now() - INTERVAL 7 DAY
        AND lib IS NOT NULL
        AND lib_version IS NOT NULL
    GROUP BY lib, lib_version
    ORDER BY
        lib,
        sortableSemVer(lib_version) DESC,
        event_count DESC
""")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def run_query(team: Team) -> HogQLQueryResponse:
    query_type = "sdk_versions_for_team"
    with tags_context(
        product=Product.SDK_DOCTOR,
        feature=Feature.HEALTH_CHECK,
        team_id=team.pk,
        org_id=team.organization_id,
        query_type=query_type,
    ):
        response = execute_hogql_query(QUERY, team, query_type=query_type)
    return response


def get_sdk_versions_for_team(
    team_id: int,
    *,
    logger: BoundLogger = default_logger,
) -> dict[str, list[SdkVersionEntry]] | None:
    """
    Query ClickHouse for events in the last 7 days and extract SDK usage.
    Returns dict of SDK versions with minimal data, grouped by lib type.
    """
    try:
        team = Team.objects.get(id=team_id)
        response = run_query(team)

        output = defaultdict(list)
        for lib, lib_version, max_timestamp, event_count in response.results:
            if lib in SDK_TYPES:
                output[lib].append(
                    {
                        "lib_version": lib_version,
                        "max_timestamp": str(max_timestamp),
                        "count": event_count,
                    }
                )

        return dict(output)
    except Team.DoesNotExist:
        logger.exception(f"[SDK Doctor] Team {team_id} not found")
        return {}  # Safe to return empty dict, this is not an error
    except Exception as e:
        logger.exception(f"[SDK Doctor] Error querying events for team {team_id}")
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
    Used by the SDK Doctor API for on-demand cache-miss fallback.
    Returns the response data dict or None if failed.
    """
    try:
        sdk_versions = get_sdk_versions_for_team(team_id, logger=logger)
        if sdk_versions is not None:
            payload = json.dumps(sdk_versions)
            cache_key = team_sdk_versions_key(team_id)
            redis_client.setex(cache_key, SDK_CACHE_EXPIRY, payload)
            logger.info(f"[SDK Doctor] Team {team_id} SDK versions cached successfully")

            return sdk_versions
        else:
            logger.error(f"[SDK Doctor] No data received from ClickHouse for team {team_id}")
            return None
    except Exception as e:
        logger.exception(f"[SDK Doctor] Failed to get and cache SDK versions for team {team_id}")
        capture_exception(e)
        return None
