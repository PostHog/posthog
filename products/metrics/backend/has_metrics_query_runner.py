import datetime as dt

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.errors import CHQueryErrorUnknownTable
from posthog.models import Team

HAS_METRICS_CACHE_TTL = int(dt.timedelta(days=7).total_seconds())


class HasMetricsQueryRunner:
    def __init__(self, team: Team) -> None:
        self.team = team

    def run(self) -> bool:
        # `metrics` is only registered under the `posthog.` HogQL namespace
        # (posthog/hogql/database/database.py), so unlike `logs` it must be
        # referenced fully qualified.
        query = parse_select("SELECT 1 FROM posthog.metrics LIMIT 1")
        assert isinstance(query, ast.SelectQuery)

        try:
            response = execute_hogql_query(
                query_type="HasMetricsQuery",
                query=query,
                team=self.team,
                workload=Workload.LOGS,
            )
        except CHQueryErrorUnknownTable:
            # The metrics tables are provisioned out-of-band per environment;
            # an environment without them simply has no metrics yet.
            return False

        return len(response.results) > 0


def team_has_metrics(team: Team) -> bool:
    cache_key = f"team:{team.id}:has_metrics"
    if cache.get(cache_key) is True:
        return True

    has_metrics = HasMetricsQueryRunner(team).run()
    if has_metrics:
        cache.set(cache_key, True, HAS_METRICS_CACHE_TTL)
    return has_metrics
