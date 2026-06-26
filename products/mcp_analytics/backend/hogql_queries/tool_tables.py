"""Per-tool "Top users" and "Failures" tables for the MCP analytics tool detail page.

Both resolve the client harness to a customer label server-side via `mcp_harness`
(the single source of truth) so the tool-detail surface shows the same labelling as
the dashboard donut — the frontend only maps a resolved label to its logo.
"""

from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPToolFailuresQueryResponse,
    CachedMCPToolTopUsersQueryResponse,
    MCPToolFailureItem,
    MCPToolFailuresQuery,
    MCPToolFailuresQueryResponse,
    MCPToolTopUserItem,
    MCPToolTopUsersQuery,
    MCPToolTopUsersQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend import mcp_harness
from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import mcp_query_date_range, validate_mcp_analytics_access

if TYPE_CHECKING:
    from posthog.models.user import User

# The new SDK source marker, and the *effective* tool name (the inner tool when the
# call went through the single-exec wrapper, else the directly-registered tool name).
# Mirrors EFFECTIVE_TOOL_HOGQL / NEW_SDK_FILTER in the tool-detail frontend logic.
_NEW_SDK_SOURCE = "posthog_mcp_analytics"
_EFFECTIVE_TOOL = (
    "coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))"
)

# A per-row distinct-and-sorted list of resolved harness labels, collected from the
# token computed in the inner subquery. groupArray evaluates the label per row, so the
# token only has to be materialized once as `h`.
_HARNESS_LABELS_AGG = f"arraySort(arrayDistinct(groupArray({mcp_harness.harness_label_sql('h')})))"


class MCPToolTopUsersQueryRunner(AnalyticsQueryRunner[MCPToolTopUsersQueryResponse]):
    query: MCPToolTopUsersQuery
    cached_response: CachedMCPToolTopUsersQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def _where(self) -> ast.Expr:
        return ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                parse_expr(
                    "{effective_tool} = {tool}",
                    placeholders={
                        "effective_tool": parse_expr(_EFFECTIVE_TOOL),
                        "tool": ast.Constant(value=self.query.toolName),
                    },
                ),
                parse_expr(
                    "properties.$mcp_source = {source}", placeholders={"source": ast.Constant(value=_NEW_SDK_SOURCE)}
                ),
            ]
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                distinct_id,
                argMax(person_properties, timestamp) AS person_properties,
                count() AS calls,
                countIf(is_error) AS errors,
                round(countIf(is_error) * 100.0 / count(), 1) AS error_rate_pct,
                {labels_agg} AS harnesses,
                max(timestamp) AS last_seen
            FROM (
                SELECT
                    distinct_id,
                    timestamp,
                    toBool(properties.$mcp_is_error) AS is_error,
                    toString(person.properties) AS person_properties,
                    {token} AS h
                FROM events
                WHERE {where}
            )
            GROUP BY distinct_id
            ORDER BY calls DESC
            LIMIT 5
            """,
            placeholders={
                "labels_agg": parse_expr(_HARNESS_LABELS_AGG),
                "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                "where": self._where(),
            },
        )

    def _calculate(self) -> MCPToolTopUsersQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_top_users_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_tool_top_users_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolTopUserItem(
                distinct_id=str(row[0]),
                person_properties=str(row[1] or ""),
                calls=int(row[2] or 0),
                errors=int(row[3] or 0),
                error_rate_pct=float(row[4] or 0),
                harnesses=[str(h) for h in (row[5] or [])],
                last_seen=str(row[6] or ""),
            )
            for row in (response.results or [])
        ]
        return MCPToolTopUsersQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


class MCPToolFailuresQueryRunner(AnalyticsQueryRunner[MCPToolFailuresQueryResponse]):
    query: MCPToolFailuresQuery
    cached_response: CachedMCPToolFailuresQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def _where(self) -> ast.Expr:
        # $exception events don't carry the new-SDK markers ($mcp_source / $mcp_exec_tool_call_name),
        # so this matches the raw $mcp_tool_name rather than the effective tool name.
        return ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value="$exception")}),
                parse_expr(
                    "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                parse_expr(
                    "toString(properties.$mcp_tool_name) = {tool}",
                    placeholders={"tool": ast.Constant(value=self.query.toolName)},
                ),
                parse_expr("notEmpty(toString(properties.$exception_message))"),
            ]
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                message,
                count() AS occurrences,
                max(timestamp) AS last_seen,
                {labels_agg} AS harnesses
            FROM (
                SELECT
                    substring(toString(properties.$exception_message), 1, 200) AS message,
                    timestamp,
                    {token} AS h
                FROM events
                WHERE {where}
            )
            GROUP BY message
            ORDER BY occurrences DESC
            LIMIT 20
            """,
            placeholders={
                "labels_agg": parse_expr(_HARNESS_LABELS_AGG),
                "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                "where": self._where(),
            },
        )

    def _calculate(self) -> MCPToolFailuresQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_failures_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_tool_failures_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolFailureItem(
                message=str(row[0] or ""),
                occurrences=int(row[1] or 0),
                last_seen=str(row[2] or ""),
                harnesses=[str(h) for h in (row[3] or [])],
            )
            for row in (response.results or [])
        ]
        return MCPToolFailuresQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
