import datetime as dt

from django.core.cache import cache

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

logger = structlog.get_logger(__name__)

HAS_LOGS_CACHE_TTL = int(dt.timedelta(days=7).total_seconds())
# Shorter TTL used only when the underlying query *errored* (e.g. the logs
# ClickHouse table or workload isn't provisioned on a self-hosted instance).
# We don't cache the "ran successfully but no rows yet" case so that newly
# ingested logs surface immediately in the UI.
HAS_LOGS_ERROR_CACHE_TTL = int(dt.timedelta(minutes=5).total_seconds())
# Sentinel value distinct from a regular False so we only suppress the
# ClickHouse query when it previously errored, not when it returned no rows.
HAS_LOGS_ERROR_SENTINEL = "error"


def _has_logs_cache_key(team: Team) -> str:
    return f"team:{team.id}:has_logs"


class HasLogsQueryRunner:
    def __init__(self, team: Team):
        self.team = team

    def run(self) -> bool:
        query = parse_select("SELECT 1 FROM logs LIMIT 1")
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="HasLogsQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
        )

        return len(response.results) > 0


def team_has_logs(team: Team) -> bool:
    """Return True iff the team has at least one log entry.

    Falls back to False (rather than raising) when the underlying ClickHouse
    query fails — typically because a self-hosted instance hasn't provisioned
    the logs cluster. Errored answers are cached briefly to avoid hammering
    ClickHouse on every probe while the misconfiguration is in place.
    """
    cache_key = _has_logs_cache_key(team)
    cached = cache.get(cache_key)
    if cached is True:
        return True
    if cached == HAS_LOGS_ERROR_SENTINEL:
        return False

    try:
        has_logs = HasLogsQueryRunner(team).run()
    except Exception:
        logger.exception("has_logs_query_failed", team_id=team.id)
        mark_logs_unavailable(team)
        return False

    if has_logs:
        cache.set(cache_key, True, HAS_LOGS_CACHE_TTL)
    return has_logs


def logs_marked_unavailable(team: Team) -> bool:
    """Cheap (cache-only) check used by query endpoints to short-circuit when
    a previous probe or query already determined the logs cluster is misconfigured.

    Does NOT issue any ClickHouse query, so it's safe to call on every request.
    """
    return cache.get(_has_logs_cache_key(team)) == HAS_LOGS_ERROR_SENTINEL


def mark_logs_unavailable(team: Team) -> None:
    """Mark the logs cluster as unavailable for this team. Used after a query
    endpoint has caught a ClickHouse error so subsequent requests short-circuit
    via the cache rather than re-running the failing query."""
    cache.set(_has_logs_cache_key(team), HAS_LOGS_ERROR_SENTINEL, HAS_LOGS_ERROR_CACHE_TTL)
