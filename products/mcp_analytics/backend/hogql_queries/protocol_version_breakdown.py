from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPProtocolVersionBreakdownQueryResponse,
    MCPProtocolVersionBreakdownItem,
    MCPProtocolVersionBreakdownQuery,
    MCPProtocolVersionBreakdownQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import (
    mcp_query_date_range,
    shared_filter_exprs,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.models.user import User


# Existing projects have this property typed DateTime (ingestion inferred it from the date-shaped
# values), so properties.$mcp_protocol_version reads "2025-06-18" back as a timestamp. Read the raw string.
PROTOCOL_VERSION_SQL = "JSONExtractString(properties, '$mcp_protocol_version')"

# Matches the SDKs' era rule: revisions are dated, and the rolling draft sits ahead of all of them.
CURRENT_PROTOCOL_REVISION = "2026-07-28"
IS_DATED_SQL = r"match(protocol_version, '^\\d{4}-\\d{2}-\\d{2}$')"

PROTOCOL_VERSION_SERIES_LIMIT = 8


class MCPProtocolVersionBreakdownQueryRunner(AnalyticsQueryRunner[MCPProtocolVersionBreakdownQueryResponse]):
    query: MCPProtocolVersionBreakdownQuery
    cached_response: CachedMCPProtocolVersionBreakdownQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def _where(self) -> ast.Expr:
        exprs = [
            parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
            parse_expr(
                "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
            ),
            parse_expr("timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}),
        ]
        exprs.extend(shared_filter_exprs(self.team, self.query.properties, self.query.filterTestAccounts))
        return ast.And(exprs=exprs)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        protocol_version_totals = parse_select(
            """
            SELECT
                protocol_version,
                protocol_version = 'draft' OR ({is_dated} AND protocol_version >= {current_revision}) AS is_current,
                count() AS total_calls
            FROM (
                SELECT coalesce(nullIf(trim({protocol_version_sql}), ''), 'Unknown') AS protocol_version
                FROM events
                WHERE {where}
            )
            GROUP BY protocol_version
            """,
            placeholders={
                "protocol_version_sql": parse_expr(PROTOCOL_VERSION_SQL),
                "is_dated": parse_expr(IS_DATED_SQL),
                "current_revision": ast.Constant(value=CURRENT_PROTOCOL_REVISION),
                "where": self._where(),
            },
        )
        # Current revisions rank ahead of the cut so the long tail folded into 'Other' is only ever legacy.
        return parse_select(
            """
            SELECT protocol_version, is_current, total_calls
            FROM (
                SELECT
                    if(
                        protocol_version = 'Unknown', 'Unknown',
                        if(protocol_version_rank <= {limit}, protocol_version, 'Other')
                    ) AS protocol_version,
                    is_current,
                    sum(total_calls) AS total_calls
                FROM (
                    SELECT
                        protocol_version,
                        is_current,
                        total_calls,
                        row_number() OVER (
                            ORDER BY protocol_version = 'Unknown' ASC, is_current DESC, total_calls DESC, protocol_version ASC
                        ) AS protocol_version_rank
                    FROM {protocol_version_totals}
                )
                GROUP BY protocol_version, is_current
            )
            ORDER BY
                multiIf(
                    protocol_version = 'Unknown', 4,
                    protocol_version = 'Other', 3,
                    protocol_version = 'draft', 0,
                    {is_dated}, 1,
                    2
                ) ASC,
                if({is_dated}, protocol_version, '') DESC,
                total_calls DESC,
                protocol_version ASC
            """,
            placeholders={
                "protocol_version_totals": protocol_version_totals,
                "is_dated": parse_expr(IS_DATED_SQL),
                "limit": ast.Constant(value=PROTOCOL_VERSION_SERIES_LIMIT),
            },
        )

    def _calculate(self) -> MCPProtocolVersionBreakdownQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_protocol_version_breakdown_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_protocol_version_breakdown_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        rows = response.results or []
        results = [
            MCPProtocolVersionBreakdownItem(
                protocol_version=str(row[0]), is_current=bool(row[1]), total_calls=int(row[2] or 0)
            )
            for row in rows
        ]

        return MCPProtocolVersionBreakdownQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
