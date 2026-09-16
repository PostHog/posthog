from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPOverviewSummaryQueryResponse,
    MCPOverviewSummary,
    MCPOverviewSummaryQuery,
    MCPOverviewSummaryQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.mcp_analytics.backend import mcp_harness
from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.hogql_queries.base import (
    caller_kind_expr,
    mcp_query_date_range,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.models.user import User

# A person with no call in this many days before the window reads as "new", trading perfect
# lifetime attribution for a scan bounded to a fixed lookback rather than the team's full history.
NEW_PEOPLE_LOOKBACK_DAYS = 60

# Matches MCPToolStatsQueryRunner's with_intent expression, so the two surfaces agree on what
# counts as "has an intent".
_HAS_INTENT = "(notEmpty(toString(properties.$mcp_intent)) AND toString(properties.$mcp_intent) != '{}')"

# Computed twice in the same SELECT (once as the numerator's guard, once as the divisor); kept as
# one HogQL fragment so both call sites can't drift from each other.
_NEW_PEOPLE_COUNT = "uniqIf(person_id, is_new)"


class MCPOverviewSummaryQueryRunner(AnalyticsQueryRunner[MCPOverviewSummaryQueryResponse]):
    """Top-line KPIs for the MCP analytics overview page.

    A person is "new" when they have no recorded call in the NEW_PEOPLE_LOOKBACK_DAYS
    immediately before the window: equivalent to their first-ever call inside that lookback
    landing inside the window, since a person already known to have called in the window must
    have some first call somewhere within it.
    """

    query: MCPOverviewSummaryQuery
    cached_response: CachedMCPOverviewSummaryQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def _segment_exprs(self, *, caller_kind: str | None) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []
        kind_expr = caller_kind_expr(caller_kind)
        if kind_expr is not None:
            exprs.append(kind_expr)
        properties = list(self.query.properties or [])
        if self.query.filterTestAccounts:
            properties += self.team.test_account_filters or []
        if properties:
            exprs.append(property_to_expr(properties, self.team))
        return exprs

    def _where(self) -> ast.Expr:
        return ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {date_from}",
                    placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                *self._segment_exprs(caller_kind=self.query.callerKind),
            ]
        )

    def _lookback_where(self) -> ast.Expr:
        return ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {lookback_from}",
                    placeholders={
                        "lookback_from": parse_expr(
                            "{date_from} - toIntervalDay({days})",
                            placeholders={
                                "date_from": self.query_date_range.date_from_as_hogql(),
                                "days": ast.Constant(value=NEW_PEOPLE_LOOKBACK_DAYS),
                            },
                        )
                    },
                ),
                parse_expr(
                    "timestamp < {date_from}",
                    placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
                ),
                *self._segment_exprs(caller_kind=self.query.callerKind),
            ]
        )

    def _automation_where(self) -> ast.Expr:
        return ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {date_from}",
                    placeholders={"date_from": self.query_date_range.date_from_as_hogql()},
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                *self._segment_exprs(caller_kind="automations"),
            ]
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                uniq(person_id) AS people,
                {new_people_count} AS new_people,
                uniqIf(person_id, NOT is_new) AS returning_people,
                round(
                    if({new_people_count} = 0, 0,
                        countIf(is_new AND is_first_call AND is_error) * 100.0 / {new_people_count}),
                    1
                ) AS new_people_first_call_failed_pct,
                count() AS calls,
                countDistinctIf(session_id, session_id != '') AS sessions,
                round(100 - (countIf(is_error) * 100.0 / count()), 1) AS success_pct,
                round(countIf(has_intent) * 100.0 / count(), 1) AS intent_pct,
                uniq({label}) AS clients
            FROM (
                SELECT
                    person_id,
                    $session_id AS session_id,
                    toBool(properties.$mcp_is_error) AS is_error,
                    {has_intent} AS has_intent,
                    {token} AS h,
                    person_id NOT IN (SELECT person_id FROM events WHERE {lookback_where}) AS is_new,
                    row_number() OVER (PARTITION BY person_id ORDER BY timestamp) = 1 AS is_first_call
                FROM events
                WHERE {where}
            )
            """,
            placeholders={
                "new_people_count": parse_expr(_NEW_PEOPLE_COUNT),
                "label": parse_expr(mcp_harness.harness_label_sql("h")),
                "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                "has_intent": parse_expr(_HAS_INTENT),
                "lookback_where": self._lookback_where(),
                "where": self._where(),
            },
        )

    def _automation_totals(self) -> tuple[int, int]:
        """Calls/sessions from the complementary automated segment.

        Only meaningful once the main query already scoped to people; a second cheap aggregate
        over the same range, rather than a UNION, since the two segments never share a row.
        """
        if self.query.callerKind != "people":
            return 0, 0
        query = parse_select(
            """
            SELECT count() AS calls, countDistinctIf(session_id, session_id != '') AS sessions
            FROM (SELECT $session_id AS session_id FROM events WHERE {where})
            """,
            placeholders={"where": self._automation_where()},
        )
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_overview_summary_automation_query",
        ):
            response = execute_hogql_query(
                query=query,
                team=self.team,
                query_type="mcp_overview_summary_automation_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
        row = (response.results or [(0, 0)])[0]
        return int(row[0] or 0), int(row[1] or 0)

    def _calculate(self) -> MCPOverviewSummaryQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_overview_summary_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_overview_summary_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        row = (response.results or [None])[0]
        results: list[MCPOverviewSummary] = []
        if row and int(row[4] or 0) > 0:
            automation_calls, automation_sessions = self._automation_totals()
            results = [
                MCPOverviewSummary(
                    people=int(row[0] or 0),
                    new_people=int(row[1] or 0),
                    returning_people=int(row[2] or 0),
                    new_people_first_call_failed_pct=float(row[3] or 0),
                    calls=int(row[4] or 0),
                    sessions=int(row[5] or 0),
                    success_pct=float(row[6] or 0),
                    intent_pct=float(row[7] or 0),
                    clients=int(row[8] or 0),
                    automation_calls=automation_calls,
                    automation_sessions=automation_sessions,
                )
            ]
        return MCPOverviewSummaryQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
