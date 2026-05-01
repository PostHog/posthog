import datetime as dt

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

HAS_LOGS_CACHE_TTL = int(dt.timedelta(days=7).total_seconds())


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
    cache_key = f"team:{team.id}:has_logs"
    if cache.get(cache_key) is True:
        return True

    has_logs = HasLogsQueryRunner(team).run()
    if has_logs:
        cache.set(cache_key, True, HAS_LOGS_CACHE_TTL)
    return has_logs
