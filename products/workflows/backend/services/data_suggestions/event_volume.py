"""How often each of the project's events fired in the last week, sampled for large teams."""

import math
from collections.abc import Iterable

from posthog.schema import HogQLQueryResponse, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models import Team

# Above this many events a week the counts are sampled. The estimate itself reads 1 in 100 events.
FULL_SCAN_MAX_WEEKLY_EVENTS = 20_000_000
_ESTIMATE_SAMPLE_DENOMINATOR = 100
_COUNT_TIMEOUT_SECONDS = 30
# Sampling is by distinct ID, so the volume estimate misses a busy event that a few sampled-out IDs send, like a
# server-side event, and an exact count can then hit it. Past this many bytes a count stops and keeps the partial
# result, which still ranks the events and clears the minimum weekly count.
_COUNT_MAX_BYTES = 2_000_000_000
MAX_EVENTS = 5000
# PostHog's own events that mark a real moment, unlike the generic `$` events the planner must skip.
ALLOWED_POSTHOG_EVENTS = frozenset({"$conversation_ticket_created"})


def weekly_counts(team: Team) -> dict[str, int]:
    """How often each of the project's own events fired in the last week. PostHog's generic `$` events are left out,
    except the few that mark a real moment."""
    # Small teams get exact counts, since a quiet event could vanish from a sample. Large teams only need the
    # ranking, so a sample keeps the scan at about the size of a small team's.
    sample_denominator = max(1, math.ceil(estimated_weekly_events(team) / FULL_SCAN_MAX_WEEKLY_EVENTS))
    counts = _count_events(team, sample_denominator, skip=frozenset())
    if sample_denominator > 1:
        # A sample can miss a quiet event, like a weekly sign-up, entirely. The events table is sorted by event name
        # within a day, so an exact count that skips the events the sample found reads few rows.
        counts.update(_count_events(team, 1, skip=frozenset(counts)))
    return counts


def estimated_weekly_events(team: Team) -> int:
    query = parse_select("SELECT count() FROM events WHERE timestamp >= now() - INTERVAL 7 DAY")
    if isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(_ESTIMATE_SAMPLE_DENOMINATOR)
    response = _run_count(team, query, "workflows_data_suggestions_volume")
    rows = response.results or []
    return int(rows[0][0]) * _ESTIMATE_SAMPLE_DENOMINATOR if rows else 0


def _count_events(team: Team, sample_denominator: int, *, skip: frozenset[str]) -> dict[str, int]:
    query = parse_select(
        """
        SELECT event, count() AS weekly_count
        FROM events
        WHERE timestamp >= now() - INTERVAL 7 DAY
            AND (NOT startsWith(event, '$') OR event IN {allowed})
            AND event NOT IN {skip}
        GROUP BY event
        ORDER BY weekly_count DESC
        LIMIT {limit}
        """,
        placeholders={
            "allowed": _strings(ALLOWED_POSTHOG_EVENTS),
            # An empty tuple is not valid HogQL, so an empty skip list holds a name no event has.
            "skip": _strings(skip or {""}),
            # Without an explicit limit HogQL returns 100 rows. Events with dynamic names can reach many thousands.
            "limit": ast.Constant(value=MAX_EVENTS),
        },
    )
    if sample_denominator > 1 and isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(sample_denominator)
    response = _run_count(team, query, "workflows_data_suggestions_counts")
    return {str(row[0]): int(row[1]) * sample_denominator for row in response.results or [] if int(row[1]) > 0}


def _strings(values: Iterable[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=value) for value in sorted(values)])


def _sample(denominator: int) -> ast.SampleExpr:
    return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=denominator)))


def _run_count(team: Team, query: ast.SelectQuery | ast.SelectSetQuery, query_type: str) -> HogQLQueryResponse:
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)
    settings = HogQLGlobalSettings(
        max_execution_time=_COUNT_TIMEOUT_SECONDS,
        # A timeout must fail the run. A profile set to break would return a partial count that is cached for a week.
        timeout_overflow_mode="throw",
        max_bytes_to_read=_COUNT_MAX_BYTES,
        read_overflow_mode="break",
    )
    return execute_hogql_query(query=query, team=team, query_type=query_type, settings=settings)
