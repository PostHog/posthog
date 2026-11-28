from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.database.schema.sessions_v1 import DEFAULT_BOUNCE_RATE_DURATION_SECONDS
from posthog.hogql.parser import parse_select

from products.web_analytics.backend.hogql_queries.query_constants.sessionless_queries import SESSIONLESS_SESSIONS_QUERY

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_analytics_query_runner import WebAnalyticsQueryRunner


def build_sessionless_sessions_query(
    runner: WebAnalyticsQueryRunner, event_filters: ast.Expr | None = None
) -> ast.SelectQuery:
    """One row per session, computed from the events in the runner's periods and nothing else."""
    bounce_seconds = (
        runner.modifiers.bounceRateDurationSeconds
        if runner.modifiers and runner.modifiers.bounceRateDurationSeconds is not None
        else DEFAULT_BOUNCE_RATE_DURATION_SECONDS
    )
    query = parse_select(
        SESSIONLESS_SESSIONS_QUERY,
        timings=runner.timings,
        placeholders={
            "events_session_id_present": runner.events_session_id_present,
            "inside_timestamp_periods": runner._periods_expression("timestamp"),
            "event_filters": event_filters or ast.Constant(value=True),
            "bounce_rate_duration_seconds": ast.Constant(value=bounce_seconds),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query
