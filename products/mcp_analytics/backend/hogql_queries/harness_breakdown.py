from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPHarnessBreakdownQueryResponse,
    MCPHarnessBreakdownItem,
    MCPHarnessBreakdownQuery,
    MCPHarnessBreakdownQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend import mcp_harness
from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import (
    CONVERSATION_ID_SQL,
    effective_tool_expr,
    mcp_query_date_range,
    mcp_source_expr,
    shared_filter_exprs,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.models.user import User


class MCPHarnessBreakdownQueryRunner(AnalyticsQueryRunner[MCPHarnessBreakdownQueryResponse]):
    """MCP tool-call activity grouped by the resolved client harness.

    Powers the dashboard's harness tile and the `query-mcp-harness-breakdown` MCP
    tool from one path, so MCP clients see the same labelled, filtered data as the
    UI. The harness label is resolved server-side by `mcp_harness` (the single
    source of truth) — the inner query resolves the token once, the outer buckets
    it, so the bucketing comparisons run against a single column.
    """

    query: MCPHarnessBreakdownQuery
    cached_response: CachedMCPHarnessBreakdownQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def _base_exprs(self) -> list[ast.Expr]:
        return [
            parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
            parse_expr(
                "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
            ),
            parse_expr("timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}),
        ]

    def _where(self) -> ast.Expr:
        exprs = [
            *self._base_exprs(),
            *shared_filter_exprs(self.team, self.query.properties, self.query.filterTestAccounts),
        ]
        return ast.And(exprs=exprs)

    def _where_scoped_to_source(self) -> ast.Expr:
        # Scoped to the new-SDK source but not to one effective tool, so the outer query
        # can compute this tool's own aggregates via `is_tool` alongside the harness's
        # all-tool session total (the session-share denominator) in a single scan.
        exprs = [
            *self._base_exprs(),
            mcp_source_expr(),
            *shared_filter_exprs(self.team, self.query.properties, self.query.filterTestAccounts),
        ]
        return ast.And(exprs=exprs)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # The harness label and token are HogQL fragments from mcp_harness; parse them
        # to AST and inject as placeholders (like {where}) so nothing is string-interpolated.
        if self.query.toolName:
            return parse_select(
                """
                SELECT
                    {label} AS harness,
                    countIf(is_tool) AS total_calls,
                    countIf(is_tool AND is_error) AS errors,
                    round(countIf(is_tool AND is_error) * 100.0 / countIf(is_tool), 1) AS error_rate_pct,
                    countDistinctIf(session_id, session_id != '' AND is_tool) AS sessions,
                    countDistinctIf(session_id, session_id != '') AS harness_sessions
                FROM (
                    SELECT
                        {token} AS h,
                        {conversation_id} AS session_id,
                        toBool(properties.$mcp_is_error) AS is_error,
                        {is_tool} AS is_tool
                    FROM events
                    WHERE {where}
                )
                GROUP BY harness
                HAVING countIf(is_tool) > 0
                ORDER BY total_calls DESC
                """,
                placeholders={
                    "label": parse_expr(mcp_harness.harness_label_sql("h")),
                    "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                    "is_tool": effective_tool_expr(self.query.toolName),
                    "conversation_id": parse_expr(CONVERSATION_ID_SQL),
                    "where": self._where_scoped_to_source(),
                },
            )
        return parse_select(
            """
            SELECT
                {label} AS harness,
                count() AS total_calls,
                countIf(is_error) AS errors,
                round(countIf(is_error) * 100.0 / count(), 1) AS error_rate_pct,
                countDistinctIf(session_id, session_id != '') AS sessions
            FROM (
                SELECT
                    {token} AS h,
                    {conversation_id} AS session_id,
                    toBool(properties.$mcp_is_error) AS is_error
                FROM events
                WHERE {where}
            )
            GROUP BY harness
            ORDER BY total_calls DESC
            """,
            placeholders={
                "label": parse_expr(mcp_harness.harness_label_sql("h")),
                "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                "conversation_id": parse_expr(CONVERSATION_ID_SQL),
                "where": self._where(),
            },
        )

    def _calculate(self) -> MCPHarnessBreakdownQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_harness_breakdown_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_harness_breakdown_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPHarnessBreakdownItem(
                harness=str(row[0]),
                total_calls=int(row[1] or 0),
                errors=int(row[2] or 0),
                error_rate_pct=float(row[3] or 0),
                sessions=int(row[4] or 0),
                harness_sessions=int(row[5] or 0) if self.query.toolName else None,
            )
            for row in (response.results or [])
        ]
        return MCPHarnessBreakdownQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
