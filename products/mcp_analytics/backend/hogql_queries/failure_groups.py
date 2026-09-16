from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPFailureGroupsQueryResponse,
    MCPFailureGroup,
    MCPFailureGroupsQuery,
    MCPFailureGroupsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import (
    EFFECTIVE_TOOL_SQL,
    RAW_ERROR_TYPE_SQL,
    caller_kind_expr,
    mcp_query_date_range,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.models.user import User

DEFAULT_FAILURE_GROUPS_LIMIT = 5
MAX_FAILURE_GROUPS_LIMIT = 50

# Bounds the GROUP BY cardinality: a raw error message routinely carries a request id or a
# row count that makes two otherwise-identical failures group separately. UUIDs and runs of 4+
# digits collapse to a placeholder (3-digit runs stay, so an HTTP status still reads as itself) before grouping; the result is clipped to 200 characters,
# same as base.RAW_ERROR_TYPE_SQL's cap on the adjacent bucket.
_NORMALIZED_MESSAGE_SQL = (
    "substring("
    "replaceRegexpAll("
    "replaceRegexpAll(coalesce(toString(properties.$mcp_error_message), ''), "
    "'(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{id}'), "
    "'[0-9]{4,}', '{n}'"
    "), 1, 200)"
)

_HAS_INTENT = "(notEmpty(toString(properties.$mcp_intent)) AND toString(properties.$mcp_intent) != '{}')"


class MCPFailureGroupsQueryRunner(AnalyticsQueryRunner[MCPFailureGroupsQueryResponse]):
    """Errored MCP tool calls grouped by tool, error type, and normalized message.

    Ranked by sessions affected. For each group, also reports what the agent did immediately
    after the failing call, resolved from a window function over every call (not just errors)
    in the same session: retried the same tool and it worked, retried and it failed again,
    switched to a different tool, or the session ended there.
    """

    query: MCPFailureGroupsQuery
    cached_response: CachedMCPFailureGroupsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    @cached_property
    def limit(self) -> int:
        requested = self.query.limit if self.query.limit is not None else DEFAULT_FAILURE_GROUPS_LIMIT
        return max(1, min(requested, MAX_FAILURE_GROUPS_LIMIT))

    def _where(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
            parse_expr(
                "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
            ),
            parse_expr("timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}),
        ]
        caller_kind = caller_kind_expr(self.query.callerKind)
        if caller_kind is not None:
            exprs.append(caller_kind)
        properties = list(self.query.properties or [])
        if self.query.filterTestAccounts:
            properties += self.team.test_account_filters or []
        if properties:
            exprs.append(property_to_expr(properties, self.team))
        return ast.And(exprs=exprs)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # The CTE covers every call (not just errors) in the window, so the window function can
        # see each errored call's neighbour regardless of whether that neighbour also errored;
        # only the outer aggregate restricts to errored rows. A call with no session id is its own
        # journey: otherwise every sessionless call would share one partition and the next
        # unrelated event by timestamp would read as the agent's retry.
        return parse_select(
            """
            WITH calls AS (
                SELECT
                    $session_id AS session_id,
                    coalesce(nullIf($session_id, ''), toString(uuid)) AS journey_id,
                    timestamp,
                    person_id,
                    {effective_tool} AS tool,
                    toBool(properties.$mcp_is_error) AS is_error,
                    {raw_error_type} AS error_type,
                    {normalized_message} AS message,
                    {has_intent} AS has_intent,
                    substring(toString(properties.$mcp_intent), 1, 300) AS intent
                FROM events
                WHERE {where}
            ),
            with_next AS (
                SELECT
                    session_id,
                    journey_id,
                    person_id,
                    tool,
                    is_error,
                    error_type,
                    message,
                    has_intent,
                    intent,
                    leadInFrame(tool, 1, '') OVER (
                        PARTITION BY journey_id ORDER BY timestamp
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    ) AS next_tool,
                    leadInFrame(is_error, 1, false) OVER (
                        PARTITION BY journey_id ORDER BY timestamp
                        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                    ) AS next_is_error
                FROM calls
            )
            SELECT
                tool,
                error_type,
                message,
                countDistinctIf(session_id, session_id != '') AS sessions,
                count() AS calls,
                uniq(person_id) AS people,
                round(countIf(next_tool = tool AND NOT next_is_error) * 100.0 / count(), 1) AS next_retried_succeeded_pct,
                round(countIf(next_tool = tool AND next_is_error) * 100.0 / count(), 1) AS next_retried_failed_pct,
                round(countIf(next_tool != '' AND next_tool != tool) * 100.0 / count(), 1) AS next_switched_pct,
                round(countIf(next_tool = '') * 100.0 / count(), 1) AS next_ended_pct,
                substring(anyIf(intent, has_intent), 1, 300) AS sample_intent
            FROM with_next
            WHERE is_error
            GROUP BY tool, error_type, message
            ORDER BY sessions DESC
            LIMIT {limit}
            """,
            placeholders={
                "effective_tool": parse_expr(EFFECTIVE_TOOL_SQL),
                "raw_error_type": parse_expr(RAW_ERROR_TYPE_SQL),
                "normalized_message": parse_expr(_NORMALIZED_MESSAGE_SQL),
                "has_intent": parse_expr(_HAS_INTENT),
                "where": self._where(),
                "limit": ast.Constant(value=self.limit),
            },
        )

    def _calculate(self) -> MCPFailureGroupsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_failure_groups_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_failure_groups_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPFailureGroup(
                tool=str(row[0] or ""),
                error_type=str(row[1] or ""),
                message=str(row[2] or ""),
                sessions=int(row[3] or 0),
                calls=int(row[4] or 0),
                people=int(row[5] or 0),
                next_retried_succeeded_pct=float(row[6] or 0),
                next_retried_failed_pct=float(row[7] or 0),
                next_switched_pct=float(row[8] or 0),
                next_ended_pct=float(row[9] or 0),
                sample_intent=str(row[10] or ""),
            )
            for row in (response.results or [])
        ]
        return MCPFailureGroupsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
