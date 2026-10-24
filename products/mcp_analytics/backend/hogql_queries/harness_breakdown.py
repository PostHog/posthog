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


# The column alias for each harness identity property, by role. The query templates below
# select and group by these aliases.
_INPUT_COLUMNS: dict[str, str] = {
    "vendor_client": "harness_vendor_client",
    "legacy_vendor_client": "harness_legacy_vendor_client",
    "user_agent": "harness_user_agent",
    "client_name": "harness_client_name",
}
# Fails at import when `mcp_harness` reads a property the templates do not group by, because the
# grouped token would then merge rows that resolve to different harnesses.
if _INPUT_COLUMNS.keys() != mcp_harness.HARNESS_INPUT_PROPERTIES.keys():
    raise RuntimeError("harness_breakdown input columns are out of sync with mcp_harness.HARNESS_INPUT_PROPERTIES")


class MCPHarnessBreakdownQueryRunner(AnalyticsQueryRunner[MCPHarnessBreakdownQueryResponse]):
    """MCP tool-call activity grouped by the resolved client harness.

    Powers the dashboard's harness tile and the `query-mcp-harness-breakdown` MCP
    tool from one path, so MCP clients see the same labelled, filtered data as the
    UI. The harness label is resolved server-side by `mcp_harness` (the single
    source of truth) — the inner query resolves the token once, the outer buckets
    it, so the bucketing comparisons run against a single column.

    The token is a pure function of a few identity properties that take few distinct
    values per project, so rows are grouped by those properties first and the token
    is resolved once per group instead of once per event. Sessions are carried as
    `uniqExact` states and merged per harness, so a session that reaches one harness
    through several identity values still counts once.
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
        placeholders: dict[str, ast.Expr] = {
            "label": parse_expr(mcp_harness.harness_label_sql("h")),
            "token": parse_expr(mcp_harness.harness_token_from_inputs_sql(_INPUT_COLUMNS)),
            "conversation_id": parse_expr(CONVERSATION_ID_SQL),
            **{role: parse_expr(prop) for role, prop in mcp_harness.HARNESS_INPUT_PROPERTIES.items()},
        }
        if self.query.toolName:
            return parse_select(
                """
                SELECT
                    {label} AS harness,
                    sum(tool_calls) AS total_calls,
                    sum(tool_errors) AS errors,
                    round(sum(tool_errors) * 100.0 / sum(tool_calls), 1) AS error_rate_pct,
                    uniqExactMerge(tool_sessions) AS sessions,
                    uniqExactMerge(all_sessions) AS harness_sessions
                FROM (
                    SELECT {token} AS h, tool_calls, tool_errors, tool_sessions, all_sessions
                    FROM (
                        SELECT
                            harness_vendor_client, harness_legacy_vendor_client, harness_user_agent, harness_client_name,
                            countIf(is_tool) AS tool_calls,
                            countIf(is_tool AND is_error) AS tool_errors,
                            uniqExactState(if(session_id != '' AND is_tool, session_id, NULL)) AS tool_sessions,
                            uniqExactState(if(session_id != '', session_id, NULL)) AS all_sessions
                        FROM (
                            SELECT
                                {vendor_client} AS harness_vendor_client,
                                {legacy_vendor_client} AS harness_legacy_vendor_client,
                                {user_agent} AS harness_user_agent,
                                {client_name} AS harness_client_name,
                                {conversation_id} AS session_id,
                                toBool(properties.$mcp_is_error) AS is_error,
                                {is_tool} AS is_tool
                            FROM events
                            WHERE {where}
                        )
                        GROUP BY harness_vendor_client, harness_legacy_vendor_client, harness_user_agent, harness_client_name
                    )
                )
                GROUP BY harness
                HAVING sum(tool_calls) > 0
                ORDER BY total_calls DESC
                """,
                placeholders={
                    **placeholders,
                    "is_tool": effective_tool_expr(self.query.toolName),
                    "where": self._where_scoped_to_source(),
                },
            )
        return parse_select(
            """
            SELECT
                {label} AS harness,
                sum(calls) AS total_calls,
                sum(error_calls) AS errors,
                round(sum(error_calls) * 100.0 / sum(calls), 1) AS error_rate_pct,
                uniqExactMerge(sessions_state) AS sessions
            FROM (
                SELECT {token} AS h, calls, error_calls, sessions_state
                FROM (
                    SELECT
                        harness_vendor_client, harness_legacy_vendor_client, harness_user_agent, harness_client_name,
                        count() AS calls,
                        countIf(is_error) AS error_calls,
                        uniqExactState(if(session_id != '', session_id, NULL)) AS sessions_state
                    FROM (
                        SELECT
                            {vendor_client} AS harness_vendor_client,
                            {legacy_vendor_client} AS harness_legacy_vendor_client,
                            {user_agent} AS harness_user_agent,
                            {client_name} AS harness_client_name,
                            {conversation_id} AS session_id,
                            toBool(properties.$mcp_is_error) AS is_error
                        FROM events
                        WHERE {where}
                    )
                    GROUP BY harness_vendor_client, harness_legacy_vendor_client, harness_user_agent, harness_client_name
                )
            )
            GROUP BY harness
            ORDER BY total_calls DESC
            """,
            placeholders={**placeholders, "where": self._where()},
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
