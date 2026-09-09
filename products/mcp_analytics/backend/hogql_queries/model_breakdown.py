from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPModelBreakdownQueryResponse,
    MCPModelBreakdownItem,
    MCPModelBreakdownQuery,
    MCPModelBreakdownQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend.hogql_queries.base import (
    mcp_query_date_range,
    mcp_tool_call_where,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.models.user import User


MODEL_SERIES_LIMIT = 6


class MCPModelBreakdownQueryRunner(AnalyticsQueryRunner[MCPModelBreakdownQueryResponse]):
    query: MCPModelBreakdownQuery
    cached_response: CachedMCPModelBreakdownQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                model,
                total_calls,
                client_metadata_calls,
                self_reported_calls,
                sum(total_calls) OVER () AS all_calls,
                sum(client_metadata_calls) OVER () AS all_client_metadata_calls,
                sum(self_reported_calls) OVER () AS all_self_reported_calls
            FROM (
                SELECT
                    coalesce(nullIf(trim(toString(properties.$mcp_llm_model)), ''), '') AS model,
                    count() AS total_calls,
                    countIf(properties.$mcp_llm_model_source = 'client_metadata') AS client_metadata_calls,
                    countIf(properties.$mcp_llm_model_source = 'self_reported') AS self_reported_calls
                FROM events
                WHERE {where}
                GROUP BY model
            )
            ORDER BY model = '' DESC, total_calls DESC, model ASC
            LIMIT {limit}
            """,
            placeholders={
                "where": mcp_tool_call_where(
                    team=self.team,
                    date_range=self.query_date_range,
                    properties=self.query.properties,
                    filter_test_accounts=self.query.filterTestAccounts,
                ),
                "limit": ast.Constant(value=MODEL_SERIES_LIMIT + 1),
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

        raw_rows = response.results or []
        results: list[MCPModelBreakdownItem] = []
        if raw_rows:
            known_rows = [row for row in raw_rows if str(row[0] or "")]
            unknown_rows = [row for row in raw_rows if not str(row[0] or "")]
            displayed_rows = known_rows[:MODEL_SERIES_LIMIT] + unknown_rows

            displayed_by_model: dict[str, MCPModelBreakdownItem] = {}
            for row in displayed_rows:
                model = str(row[0] or "Unknown")
                existing = displayed_by_model.get(model)
                displayed_by_model[model] = MCPModelBreakdownItem(
                    model=model,
                    total_calls=(existing.total_calls if existing else 0) + int(row[1] or 0),
                    client_metadata_calls=(existing.client_metadata_calls if existing else 0) + int(row[2] or 0),
                    self_reported_calls=(existing.self_reported_calls if existing else 0) + int(row[3] or 0),
                )

            all_calls = int(raw_rows[0][4] or 0)
            all_client_metadata_calls = int(raw_rows[0][5] or 0)
            all_self_reported_calls = int(raw_rows[0][6] or 0)
            displayed_calls = sum(row.total_calls for row in displayed_by_model.values())
            if all_calls > displayed_calls:
                existing_other = displayed_by_model.get("Other")
                displayed_by_model["Other"] = MCPModelBreakdownItem(
                    model="Other",
                    total_calls=(existing_other.total_calls if existing_other else 0) + all_calls - displayed_calls,
                    client_metadata_calls=(existing_other.client_metadata_calls if existing_other else 0)
                    + all_client_metadata_calls
                    - sum(row.client_metadata_calls for row in displayed_by_model.values()),
                    self_reported_calls=(existing_other.self_reported_calls if existing_other else 0)
                    + all_self_reported_calls
                    - sum(row.self_reported_calls for row in displayed_by_model.values()),
                )

            results = list(displayed_by_model.values())
            results.sort(key=lambda row: (-row.total_calls, row.model))

        return MCPModelBreakdownQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
