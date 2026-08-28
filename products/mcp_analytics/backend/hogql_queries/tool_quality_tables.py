"""Query runners for the MCP analytics Tool quality tab.

The per-tool table and activity series resolve the effective tool name so exec-wrapped
calls match the per-tool detail runners. Category queries use the event-supplied category.
"""

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
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import (
    EFFECTIVE_TOOL_SQL,
    mcp_query_date_range,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
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
}


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


def _named_tool_where(
    date_range: QueryDateRange,
    categories: list[str] | None,
    *,
    tool_name: str | None = None,
) -> ast.Expr:
    """WHERE for tool-name-bearing $mcp_tool_call events in the window, filtered by category/tool."""
    exprs: list[ast.Expr] = [
        parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
        parse_expr("timestamp >= {date_from}", placeholders={"date_from": date_range.date_from_as_hogql()}),
        parse_expr("timestamp <= {date_to}", placeholders={"date_to": date_range.date_to_as_hogql()}),
        parse_expr("{tool} IS NOT NULL", placeholders={"tool": parse_expr(EFFECTIVE_TOOL_SQL)}),
        parse_expr("{tool} != ''", placeholders={"tool": parse_expr(EFFECTIVE_TOOL_SQL)}),
        *_category_in(categories),
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
    return ast.And(exprs=exprs)


class MCPToolQualityRowsQueryRunner(AnalyticsQueryRunner[MCPToolQualityRowsQueryResponse]):
    query: MCPToolQualityRowsQuery
    cached_response: CachedMCPToolQualityRowsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

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

        query = parse_select(
            """
            SELECT
                {_EFFECTIVE_TOOL} AS tool,
                count() AS total_calls,
                {_IS_ERROR} AS errors,
                round({_IS_ERROR} * 100.0 / count(), 1) AS error_rate_pct,
                {_P50} AS p50_duration_ms,
                {_P95} AS p95_duration_ms,
                {_P99} AS p99_duration_ms,
                uniq(distinct_id) AS users,
                countDistinctIf(toString(properties.$session_id), toString(properties.$session_id) != '') AS sessions,
                min(timestamp) AS first_seen,
                max(timestamp) AS last_seen,
                count() OVER () AS total_count
            FROM events
            WHERE {where}
            GROUP BY tool
            HAVING positionCaseInsensitive(tool, {search}) > 0
            ORDER BY total_calls DESC, tool ASC
            LIMIT {limit}
            OFFSET {offset}
            """,
            placeholders={
                "_EFFECTIVE_TOOL": parse_expr(EFFECTIVE_TOOL_SQL),
                "_IS_ERROR": parse_expr(_IS_ERROR),
                "_P50": parse_expr(_P50),
                "_P95": parse_expr(_P95),
                "_P99": parse_expr(_P99),
                "where": _named_tool_where(self.query_date_range, self.query.categories),
                "search": ast.Constant(value=search),
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
            total_count = int(rows[0][11] or 0) if rows else 0
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
                total_count = int(first_row[0][11] or 0) if first_row else 0
        results = [
            MCPToolQualityRowItem(
                tool=str(row[0] or ""),
                total_calls=int(row[1] or 0),
                errors=int(row[2] or 0),
                error_rate_pct=float(row[3] or 0),
                p50_duration_ms=float(row[4] or 0),
                p95_duration_ms=float(row[5] or 0),
                p99_duration_ms=float(row[6] or 0),
                users=int(row[7] or 0),
                sessions=int(row[8] or 0),
                first_seen=str(row[9] or ""),
                last_seen=str(row[10] or ""),
            )
            for row in rows
        ]
        return MCPToolQualityRowsQueryResponse(
            results=results,
            totalCount=total_count,
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
                "where": _named_tool_where(self.query_date_range, self.query.categories, tool_name=self.query.toolName),
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
