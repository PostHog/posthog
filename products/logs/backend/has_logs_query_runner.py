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
_HAS_LOGS_ERROR_SENTINEL = "error"


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
    cache_key = f"team:{team.id}:has_logs"
    cached = cache.get(cache_key)
    if cached is True:
        return True
    if cached == _HAS_LOGS_ERROR_SENTINEL:
        return False

    try:
        has_logs = HasLogsQueryRunner(team).run()
    except Exception:
        logger.exception("has_logs_query_failed", team_id=team.id)
        cache.set(cache_key, _HAS_LOGS_ERROR_SENTINEL, HAS_LOGS_ERROR_CACHE_TTL)
        return False

    if has_logs:
        cache.set(cache_key, True, HAS_LOGS_CACHE_TTL)
    return has_logs
