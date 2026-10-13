"""How often each candidate event fired in the last week, sampled for large teams."""

import math

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
# The exact recount can hit a busy event that one sampled-out distinct ID sends, like a server-side event. Past this
# many bytes it stops and keeps the partial count, which still clears the minimum weekly count.
_RECOUNT_MAX_BYTES = 2_000_000_000


def weekly_counts(team: Team, names: list[str]) -> dict[str, int]:
    if not names:
        return {}
    # Small teams get exact counts, since a quiet event could vanish from a sample. Large teams only need the
    # ranking, so a sample keeps the scan at about the size of a small team's.
    sample_denominator = max(1, math.ceil(estimated_weekly_events(team) / FULL_SCAN_MAX_WEEKLY_EVENTS))
    counts = _count_events(team, names, sample_denominator)
    missing = [name for name in names if name not in counts]
    if sample_denominator > 1 and missing:
        # A sample can miss a quiet event, like a weekly sign-up, entirely. The events table is sorted by event name
        # within a day, so an exact count of only the missing events reads few rows.
        counts.update(_count_events(team, missing, 1, max_bytes=_RECOUNT_MAX_BYTES))
    return counts


def estimated_weekly_events(team: Team) -> int:
    query = parse_select("SELECT count() FROM events WHERE timestamp >= now() - INTERVAL 7 DAY")
    if isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(_ESTIMATE_SAMPLE_DENOMINATOR)
    response = _run_count(team, query, "workflows_data_suggestions_volume")
    rows = response.results or []
    return int(rows[0][0]) * _ESTIMATE_SAMPLE_DENOMINATOR if rows else 0


def _count_events(
    team: Team, names: list[str], sample_denominator: int, *, max_bytes: int | None = None
) -> dict[str, int]:
    query = parse_select(
        """
        SELECT event, count() AS weekly_count
        FROM events
        WHERE timestamp >= now() - INTERVAL 7 DAY AND event IN {names}
        GROUP BY event
        ORDER BY weekly_count DESC
        """,
        placeholders={"names": ast.Tuple(exprs=[ast.Constant(value=name) for name in names])},
    )
    if sample_denominator > 1 and isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(sample_denominator)
    response = _run_count(team, query, "workflows_data_suggestions_counts", max_bytes=max_bytes)
    return {str(row[0]): int(row[1]) * sample_denominator for row in response.results or [] if int(row[1]) > 0}


def _sample(denominator: int) -> ast.SampleExpr:
    return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=denominator)))


def _run_count(
    team: Team, query: ast.SelectQuery | ast.SelectSetQuery, query_type: str, *, max_bytes: int | None = None
) -> HogQLQueryResponse:
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)
    settings = HogQLGlobalSettings(
        max_execution_time=_COUNT_TIMEOUT_SECONDS,
        max_bytes_to_read=max_bytes,
        read_overflow_mode="break" if max_bytes is not None else None,
    )
    return execute_hogql_query(query=query, team=team, query_type=query_type, settings=settings)
