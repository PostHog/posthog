from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPModelBreakdownQueryResponse,
    MCPModelBreakdownItem,
    MCPModelBreakdownQuery,
    MCPModelBreakdownQueryResponse,
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
    from posthog.models.user import User


MODEL_SERIES_LIMIT = 6
MODEL_PAGE_SIZE = 50
MODEL_MAX_PAGE_SIZE = 100


class MCPModelBreakdownQueryRunner(AnalyticsQueryRunner[MCPModelBreakdownQueryResponse]):
    query: MCPModelBreakdownQuery
    cached_response: CachedMCPModelBreakdownQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    @cached_property
    def page_size(self) -> int:
        return max(1, min(self.query.limit if self.query.limit is not None else MODEL_PAGE_SIZE, MODEL_MAX_PAGE_SIZE))

    def _where(self) -> ast.Expr:
        exprs = [
            parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
            parse_expr(
                "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
            ),
            parse_expr("timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}),
        ]
        properties = list(self.query.properties or [])
        if self.query.filterTestAccounts:
            properties += self.team.test_account_filters or []
        if properties:
            exprs.append(property_to_expr(properties, self.team))
        return ast.And(exprs=exprs)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        model_totals = parse_select(
            """
            SELECT
                coalesce(nullIf(trim(toString(properties.$mcp_llm_model)), ''), 'Unknown') AS model,
                count() AS total_calls
            FROM events
            WHERE {where}
            GROUP BY model
            """,
            placeholders={"where": self._where()},
        )
        if self.query.includeAllModels:
            return parse_select(
                """
                SELECT model, total_calls
                FROM {model_totals}
                WHERE model != 'Unknown'
                ORDER BY total_calls DESC, model ASC
                LIMIT {limit} OFFSET {offset}
                """,
                placeholders={
                    "model_totals": model_totals,
                    "limit": ast.Constant(value=self.page_size + 1),
                    "offset": ast.Constant(value=max(0, self.query.offset or 0)),
                },
            )

        return parse_select(
            """
            SELECT
                if(model = 'Unknown', 'Unknown', if(model_rank <= {limit}, model, 'Other')) AS model_group,
                sum(total_calls) AS total_calls
            FROM (
                SELECT
                    model,
                    total_calls,
                    row_number() OVER (ORDER BY model = 'Unknown' ASC, total_calls DESC, model ASC) AS model_rank
                FROM {model_totals}
            )
            GROUP BY model_group
            ORDER BY total_calls DESC, model_group ASC
            """,
            placeholders={
                "model_totals": model_totals,
                "limit": ast.Constant(value=MODEL_SERIES_LIMIT),
            },
        )

    def _calculate(self) -> MCPModelBreakdownQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_model_breakdown_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_model_breakdown_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        rows = response.results or []
        has_more = False
        if self.query.includeAllModels:
            has_more = len(rows) > self.page_size
            rows = rows[: self.page_size]
        results = [MCPModelBreakdownItem(model=str(row[0]), total_calls=int(row[1] or 0)) for row in rows]

        return MCPModelBreakdownQueryResponse(
            results=results,
            hasMore=has_more,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
