"""Query runners for the MCP analytics dashboard's interval-bucketed charts."""

from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    AnyPropertyFilterDiscriminated,
    CachedMCPToolCallsAndErrorsQueryResponse,
    MCPToolCallsAndErrorsItem,
    MCPToolCallsAndErrorsQuery,
    MCPToolCallsAndErrorsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import mcp_query_date_range, validate_mcp_analytics_access

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

_IS_ERROR = "toBool(properties.$mcp_is_error)"


def _dashboard_where(
    date_range: QueryDateRange,
    properties: list[AnyPropertyFilterDiscriminated] | None,
    filter_test_accounts: bool | None,
    team: "Team",
) -> ast.Expr:
    """WHERE for tool-name-bearing $mcp_tool_call events in the window, plus the dashboard's filters."""
    exprs: list[ast.Expr] = [
        parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
        parse_expr("timestamp >= {date_from}", placeholders={"date_from": date_range.date_from_as_hogql()}),
        parse_expr("timestamp <= {date_to}", placeholders={"date_to": date_range.date_to_as_hogql()}),
        parse_expr("properties.$mcp_tool_name IS NOT NULL"),
        parse_expr("properties.$mcp_tool_name != ''"),
    ]
    all_properties = list(properties or [])
    if filter_test_accounts:
        all_properties += team.test_account_filters or []
    if all_properties:
        exprs.append(property_to_expr(all_properties, team))
    return ast.And(exprs=exprs)


class MCPToolCallsAndErrorsQueryRunner(AnalyticsQueryRunner[MCPToolCallsAndErrorsQueryResponse]):
    """Interval-bucketed success/error split behind the dashboard's "Tool calls and errors" chart."""

    query: MCPToolCallsAndErrorsQuery
    cached_response: CachedMCPToolCallsAndErrorsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # toString keeps the bucket a plain project-timezone wall clock. A bare dateTrunc returns a
        # typed DateTime that the query API stamps with the project's UTC offset, which the client
        # reads back as an instant and converts, shifting every bucket off the axis keys it joins
        # against. The explicit generous LIMIT stops a fine interval over a wide window from being
        # cut to the default 100 rows, which with ORDER BY bucket ASC would drop the newest buckets.
        interval = self.query.interval.value if self.query.interval else "day"
        return parse_select(
            """
            SELECT
                toString(dateTrunc({interval}, timestamp)) AS bucket,
                countIf(NOT {_IS_ERROR}) AS successes,
                countIf({_IS_ERROR}) AS errors
            FROM events
            WHERE {where}
            GROUP BY bucket
            ORDER BY bucket
            LIMIT 10000
            """,
            placeholders={
                "interval": ast.Constant(value=interval),
                "_IS_ERROR": parse_expr(_IS_ERROR),
                "where": _dashboard_where(
                    self.query_date_range,
                    self.query.properties,
                    self.query.filterTestAccounts,
                    self.team,
                ),
            },
        )

    def _calculate(self) -> MCPToolCallsAndErrorsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_calls_and_errors_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_calls_and_errors_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolCallsAndErrorsItem(
                bucket=str(row[0] or ""),
                successes=int(row[1] or 0),
                errors=int(row[2] or 0),
            )
            for row in (response.results or [])
        ]
        return MCPToolCallsAndErrorsQueryResponse(
            results=results, timings=response.timings, hogql=response.hogql, modifiers=self.modifiers
        )
