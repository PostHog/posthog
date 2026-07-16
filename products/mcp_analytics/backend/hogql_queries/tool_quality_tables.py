"""Query runners for the MCP analytics Tool quality tab.

The tab's per-tool table, aggregate activity series, and category share/counts.
Unlike the per-tool detail runners in `tool_tables.py`, these scope by the raw
`$mcp_tool_name` property (not the single-exec-resolved effective tool), matching
the tab's broad overview — the two surfaces intentionally query different populations.
"""

from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPToolCategoriesQueryResponse,
    CachedMCPToolCategoryCountsQueryResponse,
    CachedMCPToolQualityDailyStatsQueryResponse,
    CachedMCPToolQualityRowsQueryResponse,
    MCPToolCategoriesQuery,
    MCPToolCategoriesQueryResponse,
    MCPToolCategoryCountItem,
    MCPToolCategoryCountsQuery,
    MCPToolCategoryCountsQueryResponse,
    MCPToolCategoryItem,
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
from products.mcp_analytics.backend.hogql_queries.base import mcp_query_date_range, validate_mcp_analytics_access

if TYPE_CHECKING:
    from posthog.models.user import User

# The tab scopes to $mcp_tool_call events that carry a tool name. Category and tool are event-supplied
# and bound as constants (never interpolated).
_P50 = "round(quantile(0.5)(toFloat(properties.$mcp_duration_ms)))"
_P95 = "round(quantile(0.95)(toFloat(properties.$mcp_duration_ms)))"
_P99 = "round(quantile(0.99)(toFloat(properties.$mcp_duration_ms)))"
_IS_ERROR = "countIf(toBool(properties.$mcp_is_error))"


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
        parse_expr("properties.$mcp_tool_name IS NOT NULL"),
        parse_expr("properties.$mcp_tool_name != ''"),
        *_category_in(categories),
    ]
    if tool_name:
        exprs.append(
            parse_expr("properties.$mcp_tool_name = {tool}", placeholders={"tool": ast.Constant(value=tool_name)})
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

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                toString(properties.$mcp_tool_name) AS tool,
                count() AS total_calls,
                {_IS_ERROR} AS errors,
                round({_IS_ERROR} * 100.0 / count(), 1) AS error_rate_pct,
                {_P50} AS p50_duration_ms,
                {_P95} AS p95_duration_ms,
                {_P99} AS p99_duration_ms,
                uniq(distinct_id) AS users,
                countDistinctIf(toString(properties.$session_id), toString(properties.$session_id) != '') AS sessions,
                toString(min(timestamp)) AS first_seen,
                toString(max(timestamp)) AS last_seen
            FROM events
            WHERE {where}
            GROUP BY tool
            ORDER BY total_calls DESC
            LIMIT 200
            """,
            placeholders={
                "_IS_ERROR": parse_expr(_IS_ERROR),
                "_P50": parse_expr(_P50),
                "_P95": parse_expr(_P95),
                "_P99": parse_expr(_P99),
                "where": _named_tool_where(self.query_date_range, self.query.categories),
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
                query_type="mcp_tool_quality_rows_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

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
            for row in (response.results or [])
        ]
        return MCPToolQualityRowsQueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
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
                query_type="mcp_tool_categories_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [MCPToolCategoryItem(category=str(row[0] or "")) for row in (response.results or []) if row[0]]
        return MCPToolCategoriesQueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )
