import logging
import datetime as dt

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

logger = logging.getLogger(__name__)

HAS_METRICS_CACHE_TTL = int(dt.timedelta(days=7).total_seconds())


class HasMetricsQueryRunner:
    def __init__(self, team: Team) -> None:
        self.team = team

    def run(self) -> bool:
        # `metrics` is intentionally only registered under the `posthog.` namespace
        # (see posthog/hogql/database/database.py) so it isn't reachable as a bare
        # table name like `logs` is.
        query = parse_select("SELECT 1 FROM posthog.metrics LIMIT 1")
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="HasMetricsQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
        )

        return len(response.results) > 0


def team_has_metrics(team: Team) -> bool:
    cache_key = f"team:{team.id}:has_metrics:v1"
    try:
        if cache.get(cache_key) is True:
            return True
    except Exception as e:
        # Cache backend hiccup shouldn't turn the empty-state probe into a 500.
        logger.warning("has_metrics cache read failed for team %s: %s", team.id, e)

    try:
        has_metrics = HasMetricsQueryRunner(team).run()
    except Exception as e:
        # ClickHouse unavailable, table not yet provisioned in this env, etc.
        # Surface the error to Sentry but fail closed (no metrics) so the UI
        # can show the setup prompt instead of a crashed editor.
        logger.warning("HasMetricsQueryRunner failed for team %s: %s", team.id, e)
        capture_exception(e)
        return False

    if has_metrics:
        try:
            cache.set(cache_key, True, HAS_METRICS_CACHE_TTL)
        except Exception as e:
            logger.warning("has_metrics cache write failed for team %s: %s", team.id, e)
    return has_metrics
