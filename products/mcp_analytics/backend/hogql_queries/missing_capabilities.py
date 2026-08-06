"""The missing-capabilities feed: every `$mcp_missing_capability` report, newest first.

When a server enables `reportMissing`, the SDK registers a virtual `get_more_tools`
tool; an agent that calls it says, in its own words, what it wanted and could not
get. That text lands in `$mcp_intent` and is the most direct product signal the
dataset carries — "your agents wanted X and you don't support it".

Chronological, deliberately not aggregated: per-team volumes are small (median ~3
reports in 30 days) and agents almost never repeat an ask verbatim, so grouping on
the text would return a wall of count-1 rows. Semantic clustering is a separate job.
"""

from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPMissingCapabilitiesQueryResponse,
    MCPMissingCapabilitiesItem,
    MCPMissingCapabilitiesQuery,
    MCPMissingCapabilitiesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend import mcp_harness
from products.mcp_analytics.backend.constants import MCP_MISSING_CAPABILITY_EVENT
from products.mcp_analytics.backend.hogql_queries.base import (
    display_person_properties,
    mcp_query_date_range,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.models.user import User

# Matches the session-list bounds so both feeds page the same way.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

# The report text itself. Referenced twice — as the returned column and as the search
# target — so the two can't drift onto different properties.
_REPORT_TEXT = "toString(properties.$mcp_intent)"

# Conversation id, same resolution as the tool-call surfaces: the SDK's own
# $mcp_session_id when set, else the ambient $session_id.
_CONVERSATION_ID = "coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id))"


class MCPMissingCapabilitiesQueryRunner(AnalyticsQueryRunner[MCPMissingCapabilitiesQueryResponse]):
    """Chronological feed of the capabilities agents asked for and could not get.

    Powers the "Missing capabilities" tab and the `query-mcp-missing-capabilities` MCP
    tool from one path. The client label is resolved server-side by `mcp_harness`; unlike the
    aggregating runners this one uses `harness_label_or_token_sql`, because a report
    row is a single event, not a grouping key: an unrecognized client is worth naming
    verbatim, and a report that carries no client identity at all (common — the SDK
    only stamps `$mcp_client_name` on `$mcp_initialize`) must be distinguishable from
    a client we merely failed to recognize, which "Other" would hide.
    """

    query: MCPMissingCapabilitiesQuery
    cached_response: CachedMCPMissingCapabilitiesQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    @cached_property
    def limit(self) -> int:
        return min(self.query.limit or DEFAULT_LIMIT, MAX_LIMIT)

    @cached_property
    def offset(self) -> int:
        return max(self.query.offset or 0, 0)

    def _where(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_MISSING_CAPABILITY_EVENT)}),
            parse_expr(
                "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
            ),
            parse_expr("timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}),
        ]
        term = (self.query.search or "").strip()
        if term:
            # ILIKE, the product's case-insensitive substring idiom; the term is bound
            # as a constant so a `%` in the user's text can only widen their own match.
            exprs.append(
                parse_expr(
                    "{report_text} ILIKE {search}",
                    placeholders={
                        "report_text": parse_expr(_REPORT_TEXT),
                        "search": ast.Constant(value=f"%{term}%"),
                    },
                )
            )
        return ast.And(exprs=exprs)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # The harness fragments are HogQL text from mcp_harness; parse them to AST and inject
        # as placeholders so nothing is string-interpolated. The token is computed once as a
        # column in the inner query and the label buckets that column, per mcp_harness's contract.
        return parse_select(
            """
            SELECT
                toString(timestamp) AS timestamp,
                intent,
                {harness_label} AS harness,
                session_id,
                distinct_id,
                person_email,
                person_name
            FROM (
                SELECT
                    timestamp,
                    {report_text} AS intent,
                    {conversation_id} AS session_id,
                    distinct_id,
                    toString(person.properties.email) AS person_email,
                    toString(person.properties.name) AS person_name,
                    {token} AS h,
                    {display_name} AS client_display
                FROM events
                WHERE {where}
            )
            ORDER BY timestamp DESC
            LIMIT {limit} OFFSET {offset}
            """,
            placeholders={
                "harness_label": parse_expr(mcp_harness.harness_label_or_token_sql("h", "client_display")),
                "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                "display_name": parse_expr(mcp_harness.HARNESS_DISPLAY_NAME_SQL),
                "report_text": parse_expr(_REPORT_TEXT),
                "conversation_id": parse_expr(_CONVERSATION_ID),
                "where": self._where(),
                # Over-fetch one row to learn whether a next page exists, without a count
                # query — the same trick the sessions list uses.
                "limit": ast.Constant(value=self.limit + 1),
                "offset": ast.Constant(value=self.offset),
            },
        )

    def _calculate(self) -> MCPMissingCapabilitiesQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_missing_capabilities_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_missing_capabilities_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        rows = response.results or []
        has_next = len(rows) > self.limit
        results = [
            MCPMissingCapabilitiesItem(
                timestamp=str(row[0] or ""),
                intent=str(row[1] or ""),
                harness=str(row[2] or ""),
                session_id=str(row[3] or ""),
                distinct_id=str(row[4] or ""),
                # Only the fields the person cell renders, not the whole properties blob.
                person_properties=display_person_properties(email=str(row[5] or ""), name=str(row[6] or "")),
            )
            for row in rows[: self.limit]
        ]
        return MCPMissingCapabilitiesQueryResponse(
            results=results,
            has_next=has_next,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
