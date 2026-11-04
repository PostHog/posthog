"""The ClickHouse read behind the log pattern feed: each pattern's first bucket in a window."""

import datetime as dt
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.logs.backend.logs_query_runner import fail_fast_aggregate_settings


def first_sightings(team_id: int, since: dt.datetime, until: dt.datetime, limit: int) -> list[tuple[Any, ...]]:
    """Rows of (service, severity, version, pattern, environment, namespace, first bucket, last bucket), earliest first."""
    team = Team.objects.get(id=team_id)
    select = parse_select(
        """
        SELECT service_name, severity_text, pattern_version, pattern,
               argMin(environment, time_bucket), argMin(namespace, time_bucket), min(time_bucket) AS first_bucket,
               max(time_bucket)
        FROM posthog.logs_pattern_buckets
        WHERE time_bucket >= {since} AND time_bucket < {until}
        GROUP BY service_name, severity_text, pattern_version, pattern
        ORDER BY first_bucket
        LIMIT {limit}
        """,
        placeholders={
            "since": ast.Constant(value=since),
            "until": ast.Constant(value=until),
            "limit": ast.Constant(value=limit),
        },
    )
    response = execute_hogql_query(
        query_type="LogsPatternsAppearance",
        query=select,
        team=team,
        workload=Workload.LOGS,
        settings=fail_fast_aggregate_settings(),
    )
    return [tuple(row) for row in response.results]
