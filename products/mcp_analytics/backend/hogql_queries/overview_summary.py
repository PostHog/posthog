from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPOverviewSummaryQueryResponse,
    MCPOverviewSummaryQuery,
    MCPOverviewSummaryQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend.hogql_queries.base import mcp_query_date_range, validate_mcp_analytics_access

if TYPE_CHECKING:
    from posthog.models.user import User


class MCPOverviewSummaryQueryRunner(AnalyticsQueryRunner[MCPOverviewSummaryQueryResponse]):
    """Top-line KPIs for the MCP analytics overview page.

    Wired ahead of its HogQL body so the frontend can start against a stable schema; the
    query itself lands in a follow-up commit.
    """

    query: MCPOverviewSummaryQuery
    cached_response: CachedMCPOverviewSummaryQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select("SELECT 1 WHERE 1 = 0")

    def _calculate(self) -> MCPOverviewSummaryQueryResponse:
        return MCPOverviewSummaryQueryResponse(results=[])
