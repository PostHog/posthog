"""Query runners for the MCP analytics Tool quality tab.

The per-tool table and activity series resolve the effective tool name so exec-wrapped
calls match the per-tool detail runners. Category queries use the event-supplied category.
"""

from collections.abc import Sequence
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Literal, cast

from posthog.schema import (
    CachedMCPToolCategoriesQueryResponse,
    CachedMCPToolCategoryCountsQueryResponse,
    CachedMCPToolCategoryMapQueryResponse,
    CachedMCPToolQualityDailyStatsQueryResponse,
    CachedMCPToolQualityRowsQueryResponse,
    MCPToolCategoriesQuery,
    MCPToolCategoriesQueryResponse,
    MCPToolCategoryCountItem,
    MCPToolCategoryCountsQuery,
    MCPToolCategoryCountsQueryResponse,
    MCPToolCategoryItem,
    MCPToolCategoryMapItem,
    MCPToolCategoryMapQuery,
    MCPToolCategoryMapQueryResponse,
    MCPToolQualityDailyStatItem,
    MCPToolQualityDailyStatsQuery,
    MCPToolQualityDailyStatsQueryResponse,
    MCPToolQualityRowItem,
    MCPToolQualityRowsQuery,
    MCPToolQualityRowsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import DateRangeBounds, QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import (
    CONVERSATION_ID_SQL,
    EFFECTIVE_TOOL_SQL,
    mcp_query_date_range,
    shared_filter_exprs,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.schema import AnyPropertyFilterDiscriminated

    from posthog.models.team import Team
    from posthog.models.user import User

# The tab scopes to $mcp_tool_call events that carry a tool name. Category and tool are event-supplied
# and bound as constants (never interpolated).
_P50 = "round(quantile(0.5)(toFloat(properties.$mcp_duration_ms)))"
_P95 = "round(quantile(0.95)(toFloat(properties.$mcp_duration_ms)))"
_P99 = "round(quantile(0.99)(toFloat(properties.$mcp_duration_ms)))"
_IS_ERROR = "countIf(toBool(properties.$mcp_is_error))"
_TOOL_ROW_DEFAULT_LIMIT = 50
_TOOL_ROW_MAX_LIMIT = 100
_TOOL_SORT_COLUMNS = {
    "total_calls",
    "error_rate_pct",
    "p50_duration_ms",
    "p95_duration_ms",
    "p99_duration_ms",
    "users",
    "sessions",
    "last_seen",
    "trend_score",
}
# Smoothing for the trend sort key, (calls - previous) / (previous + k). Without it a tool going
# from 2 to 40 calls outranks one going from 200 to 5,000. k scales with overall volume so the
# same ranking holds for small and large projects.
_TREND_SCORE_MIN_K = 10
_TREND_SCORE_VOLUME_FRACTION = 0.0001


def _category_in(categories: list[str] | None) -> list[ast.Expr]:
    """Optional `$mcp_tool_category IN (...)` predicate, values bound as constants."""
    if not categories:
        return []
    return [
        parse_expr(
            "properties.$mcp_tool_category IN {categories}",
            placeholders={"categories": ast.Tuple(exprs=[ast.Constant(value=c) for c in categories])},
        )
    ]


def _within(date_from: ast.Expr, date_to: ast.Expr, *, exclusive_end: bool = False) -> ast.Expr:
    return parse_expr(
        "timestamp >= {date_from} AND timestamp < {date_to}"
        if exclusive_end
        else "timestamp >= {date_from} AND timestamp <= {date_to}",
        placeholders={"date_from": date_from, "date_to": date_to},
    )


def _hogql_datetime(value: datetime) -> ast.Expr:
    return ast.Call(name="toDateTime", args=[ast.Constant(value=value.strftime("%Y-%m-%d %H:%M:%S"))])


def _named_tool_where(
    time_window: ast.Expr,
    categories: list[str] | None,
    team: "Team",
    properties: "Sequence[AnyPropertyFilterDiscriminated] | None" = None,
    filter_test_accounts: bool | None = None,
    *,
    tool_name: str | None = None,
    search: str | None = None,
) -> ast.Expr:
    """Apply tool-name filters before aggregation so non-matching events skip the percentile and distinct aggregates."""
    exprs: list[ast.Expr] = [
        parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
        time_window,
        parse_expr("{tool} IS NOT NULL", placeholders={"tool": parse_expr(EFFECTIVE_TOOL_SQL)}),
        parse_expr("{tool} != ''", placeholders={"tool": parse_expr(EFFECTIVE_TOOL_SQL)}),
        *_category_in(categories),
        *shared_filter_exprs(team, properties, filter_test_accounts),
    ]
    if tool_name:
        exprs.append(
            parse_expr(
                "{effective_tool} = {tool}",
                placeholders={
                    "effective_tool": parse_expr(EFFECTIVE_TOOL_SQL),
                    "tool": ast.Constant(value=tool_name),
                },
            )
        )
    if search:
        exprs.append(
            parse_expr(
                "positionCaseInsensitive({effective_tool}, {search}) > 0",
                placeholders={
                    "effective_tool": parse_expr(EFFECTIVE_TOOL_SQL),
                    "search": ast.Constant(value=search),
                },
            )
        )
    return ast.And(exprs=exprs)


class MCPToolQualityRowsQueryRunner(AnalyticsQueryRunner[MCPToolQualityRowsQueryResponse]):
    query: MCPToolQualityRowsQuery
    cached_response: CachedMCPToolQualityRowsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    @cached_property
    def previous_window(self) -> DateRangeBounds:
        """The period the Trend column compares against, as a half-open [date_from, date_to).

        To-date ranges ("This month") compare against the same part of the previous unit. Every
        other range compares against the same length of time right before the current window.
        """
        current_from = self.query_date_range.date_from()
        current_to = self.query_date_range.date_to()
        calendar = QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange, team=self.team, interval=None, now=self.query_date_range.now_with_timezone
        ).previous_calendar_period(current_from, current_to)
        if calendar is not None:
            return calendar
        return DateRangeBounds(date_from=current_from - (current_to - current_from), date_to=current_from)

    def to_query(
        self, *, limit_override: int | None = None, offset_override: int | None = None
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        requested_limit = limit_override if limit_override is not None else self.query.limit
        limit = min(max(requested_limit or _TOOL_ROW_DEFAULT_LIMIT, 1), _TOOL_ROW_MAX_LIMIT)
        offset = max(offset_override if offset_override is not None else self.query.offset or 0, 0)
        search = (self.query.search or "").strip()
        sort_column = self.query.sortColumn or "total_calls"
        if sort_column not in _TOOL_SORT_COLUMNS:
            sort_column = "total_calls"
        sort_direction = cast(Literal["ASC", "DESC"], self.query.sortDirection or "DESC")

        current_range = self.query_date_range

        query = parse_select(
            """
            SELECT
                tool,
                total_calls,
                previous_calls,
                errors,
                round(errors * 100.0 / total_calls, 1) AS error_rate_pct,
                p50_duration_ms,
                p95_duration_ms,
                p99_duration_ms,
                users,
                sessions,
                first_seen,
                last_seen,
                (total_calls - previous_calls)
                    / (previous_calls + greatest({_min_k}, round({_volume_fraction} * sum(total_calls) OVER ())))
                    AS trend_score,
                count() OVER () AS total_count,
                previous_errors,
                if(previous_calls = 0 OR isNaN(previous_p95), NULL, previous_p95) AS previous_p95_duration_ms,
                previous_sessions
            FROM (
                SELECT
                    tool,
                    countIf(is_current) AS total_calls,
                    countIf(NOT is_current) AS previous_calls,
                    countIf(is_current AND is_error) AS errors,
                    countIf(NOT is_current AND is_error) AS previous_errors,
                    round(quantileIf(0.5)(duration_ms, is_current)) AS p50_duration_ms,
                    round(quantileIf(0.95)(duration_ms, is_current)) AS p95_duration_ms,
                    round(quantileIf(0.95)(duration_ms, NOT is_current)) AS previous_p95,
                    round(quantileIf(0.99)(duration_ms, is_current)) AS p99_duration_ms,
                    uniqIf(distinct_id, is_current) AS users,
                    uniqIf(session_id, is_current) AS sessions,
                    uniqIf(session_id, NOT is_current) AS previous_sessions,
                    minIf(timestamp, is_current) AS first_seen,
                    maxIf(timestamp, is_current) AS last_seen
                FROM (
                    SELECT
                        {_EFFECTIVE_TOOL} AS tool,
                        timestamp >= {current_from} AS is_current,
                        toBool(properties.$mcp_is_error) AS is_error,
                        toFloat(properties.$mcp_duration_ms) AS duration_ms,
                        nullIf({conversation_id}, '') AS session_id,
                        distinct_id,
                        timestamp
                    FROM events
                    WHERE {where}
                )
                GROUP BY tool
                HAVING countIf(is_current) > 0
            )
            ORDER BY total_calls DESC, tool ASC
            LIMIT {limit}
            OFFSET {offset}
            """,
            placeholders={
                "_EFFECTIVE_TOOL": parse_expr(EFFECTIVE_TOOL_SQL),
                "current_from": current_range.date_from_as_hogql(),
                "conversation_id": parse_expr(CONVERSATION_ID_SQL),
                "_min_k": ast.Constant(value=_TREND_SCORE_MIN_K),
                "_volume_fraction": ast.Constant(value=_TREND_SCORE_VOLUME_FRACTION),
                # Scans only the two windows, so every row outside the current one is a previous call.
                "where": _named_tool_where(
                    self._both_windows(),
                    self.query.categories,
                    self.team,
                    self.query.properties,
                    self.query.filterTestAccounts,
                    search=search,
                ),
                "limit": ast.Constant(value=limit),
                "offset": ast.Constant(value=offset),
            },
        )
        if isinstance(query, ast.SelectQuery):
            query.order_by = [
                ast.OrderExpr(expr=ast.Field(chain=[sort_column]), order=sort_direction),
                ast.OrderExpr(expr=ast.Field(chain=["tool"]), order="ASC"),
            ]
        return query

    def _both_windows(self) -> ast.Expr:
        previous = self.previous_window
        return ast.Or(
            exprs=[
                _within(_hogql_datetime(previous.date_from), _hogql_datetime(previous.date_to), exclusive_end=True),
                _within(self.query_date_range.date_from_as_hogql(), self.query_date_range.date_to_as_hogql()),
            ]
        )

    def _total_sessions_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Ignores category and search so that narrowing the table does not turn a tool's share into 100%.
        return parse_select(
            """
            SELECT uniqIf(session_id, is_current), uniqIf(session_id, NOT is_current)
            FROM (
                SELECT nullIf({conversation_id}, '') AS session_id, timestamp >= {current_from} AS is_current
                FROM events
                WHERE {where}
            )
            """,
            placeholders={
                "conversation_id": parse_expr(CONVERSATION_ID_SQL),
                "current_from": self.query_date_range.date_from_as_hogql(),
                "where": _named_tool_where(
                    self._both_windows(),
                    None,
                    self.team,
                    self.query.properties,
                    self.query.filterTestAccounts,
                ),
            },
        )

    def _calculate(self) -> MCPToolQualityRowsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_quality_rows_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_quality_rows_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            rows = response.results or []
            total_count = int(rows[0][13] or 0) if rows else 0
            if not rows and (self.query.offset or 0) > 0:
                first_row_response = execute_hogql_query(
                    query=self.to_query(limit_override=1, offset_override=0),
                    team=self.team,
                    user=self.user,
                    query_type="mcp_tool_quality_rows_query",
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                )
                first_row = first_row_response.results or []
                total_count = int(first_row[0][13] or 0) if first_row else 0
            total_sessions_response = execute_hogql_query(
                query=self._total_sessions_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_quality_total_sessions_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
        total_sessions_row = (total_sessions_response.results or [[0, 0]])[0]
        results = [
            MCPToolQualityRowItem(
                tool=str(row[0] or ""),
                total_calls=int(row[1] or 0),
                previous_calls=int(row[2] or 0),
                errors=int(row[3] or 0),
                error_rate_pct=float(row[4] or 0),
                p50_duration_ms=float(row[5] or 0),
                p95_duration_ms=float(row[6] or 0),
                p99_duration_ms=float(row[7] or 0),
                users=int(row[8] or 0),
                sessions=int(row[9] or 0),
                first_seen=str(row[10] or ""),
                last_seen=str(row[11] or ""),
                trend_score=float(row[12] or 0),
                previous_errors=int(row[14] or 0),
                previous_p95_duration_ms=None if row[15] is None else float(row[15]),
                previous_sessions=int(row[16] or 0),
            )
            for row in rows
        ]
        return MCPToolQualityRowsQueryResponse(
            results=results,
            totalCount=total_count,
            totalSessions=int(total_sessions_row[0] or 0),
            previousTotalSessions=int(total_sessions_row[1] or 0),
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


class MCPToolQualityDailyStatsQueryRunner(AnalyticsQueryRunner[MCPToolQualityDailyStatsQueryResponse]):
    query: MCPToolQualityDailyStatsQuery
    cached_response: CachedMCPToolQualityDailyStatsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Bucket granularity comes from the frontend's getDefaultInterval so a sub-day window buckets
        # by hour/minute; dateTrunc respects the team timezone so buckets line up with the axis keys.
        # Explicit generous LIMIT so a fine interval over a wide window isn't silently cut to the
        # default 100 rows (which, with ORDER BY day ASC, would drop the most recent buckets).
        interval = self.query.interval.value if self.query.interval else "day"
        return parse_select(
            """
            SELECT
                toString(dateTrunc({interval}, timestamp)) AS day,
                count() AS calls,
                {_IS_ERROR} AS errors,
                {_P50} AS p50,
                {_P95} AS p95,
                {_P99} AS p99
            FROM events
            WHERE {where}
            GROUP BY day
            ORDER BY day
            LIMIT 10000
            """,
            placeholders={
                "interval": ast.Constant(value=interval),
                "_IS_ERROR": parse_expr(_IS_ERROR),
                "_P50": parse_expr(_P50),
                "_P95": parse_expr(_P95),
                "_P99": parse_expr(_P99),
                "where": _named_tool_where(
                    _within(self.query_date_range.date_from_as_hogql(), self.query_date_range.date_to_as_hogql()),
                    self.query.categories,
                    self.team,
                    self.query.properties,
                    self.query.filterTestAccounts,
                    tool_name=self.query.toolName,
                ),
            },
        )

    def _calculate(self) -> MCPToolQualityDailyStatsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_quality_daily_stats_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_quality_daily_stats_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolQualityDailyStatItem(
                day=str(row[0] or ""),
                calls=int(row[1] or 0),
                errors=int(row[2] or 0),
                p50=float(row[3] or 0),
                p95=float(row[4] or 0),
                p99=float(row[5] or 0),
            )
            for row in (response.results or [])
        ]
        return MCPToolQualityDailyStatsQueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )


class MCPToolCategoryCountsQueryRunner(AnalyticsQueryRunner[MCPToolCategoryCountsQueryResponse]):
    query: MCPToolCategoryCountsQuery
    cached_response: CachedMCPToolCategoryCountsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Counts every call (uncategorized included) so the share-of-usage denominator is complete.
        where = ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                *shared_filter_exprs(self.team, self.query.properties, self.query.filterTestAccounts),
            ]
        )
        return parse_select(
            """
            SELECT toString(properties.$mcp_tool_category) AS category, count() AS calls
            FROM events
            WHERE {where}
            GROUP BY category
            """,
            placeholders={"where": where},
        )

    def _calculate(self) -> MCPToolCategoryCountsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_category_counts_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_category_counts_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolCategoryCountItem(category=str(row[0] or ""), calls=int(row[1] or 0))
            for row in (response.results or [])
        ]
        return MCPToolCategoryCountsQueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )


class MCPToolCategoriesQueryRunner(AnalyticsQueryRunner[MCPToolCategoriesQueryResponse]):
    query: MCPToolCategoriesQuery
    cached_response: CachedMCPToolCategoriesQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        where = ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                parse_expr("properties.$mcp_tool_category IS NOT NULL"),
                parse_expr("properties.$mcp_tool_category != ''"),
                *shared_filter_exprs(self.team, self.query.properties, self.query.filterTestAccounts),
            ]
        )
        return parse_select(
            """
            SELECT DISTINCT toString(properties.$mcp_tool_category) AS category
            FROM events
            WHERE {where}
            ORDER BY category
            """,
            placeholders={"where": where},
        )

    def _calculate(self) -> MCPToolCategoriesQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_categories_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_categories_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [MCPToolCategoryItem(category=str(row[0] or "")) for row in (response.results or []) if row[0]]
        return MCPToolCategoriesQueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )


class MCPToolCategoryMapQueryRunner(AnalyticsQueryRunner[MCPToolCategoryMapQueryResponse]):
    query: MCPToolCategoryMapQuery
    cached_response: CachedMCPToolCategoryMapQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        where = ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                parse_expr("properties.$mcp_tool_name IS NOT NULL"),
                parse_expr("properties.$mcp_tool_name != ''"),
                parse_expr("properties.$mcp_tool_category IS NOT NULL"),
                parse_expr("properties.$mcp_tool_category != ''"),
            ]
        )
        # A tool recategorised mid-window yields a row per category rather than one arbitrary
        # winner, so the caller can decide. The limit sits well above MAX_TOOLS_IN_SNAPSHOT (300)
        # so the map always covers every tool a snapshot can name.
        return parse_select(
            """
            SELECT DISTINCT
                toString(properties.$mcp_tool_name) AS tool,
                toString(properties.$mcp_tool_category) AS category
            FROM events
            WHERE {where}
            ORDER BY tool, category
            LIMIT 2000
            """,
            placeholders={"where": where},
        )

    def _calculate(self) -> MCPToolCategoryMapQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_category_map_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_category_map_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolCategoryMapItem(tool=str(row[0] or ""), category=str(row[1] or ""))
            for row in (response.results or [])
            if row[0] and row[1]
        ]
        return MCPToolCategoryMapQueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )
