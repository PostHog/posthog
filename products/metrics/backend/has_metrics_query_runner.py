import datetime as dt

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.errors import CHQueryErrorUnknownTable
from posthog.models import Team

HAS_METRICS_CACHE_TTL = int(dt.timedelta(days=7).total_seconds())

# Negative results are cached too, but only briefly. The activation check
# (posthog/models/product_intent) reaches this from the un-throttled
# add_product_intent request path, so an uncached False is a fresh ClickHouse
# query per request — a resource-exhaustion path. The TTL stays well under the
# setup prompt's 5s poll interval (metricsSetupLogic.pollIntervalMs), so a team
# that just wired up OTel sees the no-metrics -> has-metrics flip within one
# extra poll cycle instead of being pinned to a stale empty state.
HAS_METRICS_NEGATIVE_CACHE_TTL = int(dt.timedelta(seconds=4).total_seconds())


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
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    has_metrics = HasMetricsQueryRunner(team).run()
    cache.set(cache_key, has_metrics, HAS_METRICS_CACHE_TTL if has_metrics else HAS_METRICS_NEGATIVE_CACHE_TTL)
    return has_metrics
