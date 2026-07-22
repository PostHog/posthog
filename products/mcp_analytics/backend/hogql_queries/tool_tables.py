"""Per-tool "Top users" and "Failures" tables for the MCP analytics tool detail page.

Both resolve the client harness to a customer label server-side via `mcp_harness`
(the single source of truth) so the tool-detail surface shows the same labelling as
the dashboard donut — the frontend only maps a resolved label to its logo.
"""

import json
from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMCPToolDailyStatsQueryResponse,
    CachedMCPToolDescriptionsQueryResponse,
    CachedMCPToolFailureOccurrencesQueryResponse,
    CachedMCPToolFailuresQueryResponse,
    CachedMCPToolNeighborsQueryResponse,
    CachedMCPToolSampleIntentsQueryResponse,
    CachedMCPToolStatsQueryResponse,
    CachedMCPToolTopUsersQueryResponse,
    MCPToolDailyStatItem,
    MCPToolDailyStatsQuery,
    MCPToolDailyStatsQueryResponse,
    MCPToolDescriptionItem,
    MCPToolDescriptionsQuery,
    MCPToolDescriptionsQueryResponse,
    MCPToolFailureItem,
    MCPToolFailureOccurrenceItem,
    MCPToolFailureOccurrencesQuery,
    MCPToolFailureOccurrencesQueryResponse,
    MCPToolFailuresQuery,
    MCPToolFailuresQueryResponse,
    MCPToolNeighborItem,
    MCPToolNeighborsQuery,
    MCPToolNeighborsQueryResponse,
    MCPToolSampleIntentItem,
    MCPToolSampleIntentsQuery,
    MCPToolSampleIntentsQueryResponse,
    MCPToolStatsItem,
    MCPToolStatsQuery,
    MCPToolStatsQueryResponse,
    MCPToolTopUserItem,
    MCPToolTopUsersQuery,
    MCPToolTopUsersQueryResponse,
    NeighborDirection,
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
    EFFECTIVE_TOOL_SQL,
    NEW_SDK_SOURCE,
    mcp_query_date_range,
    tool_scope_exprs,
    validate_mcp_analytics_access,
)

if TYPE_CHECKING:
    from posthog.models.user import User

# The description of the *effective* tool: for single-exec calls the inner tool's
# $mcp_exec_tool_call_description, else the directly-registered $mcp_tool_description.
# Without this, an inner tool's Descriptions table would show the exec wrapper's text
# (another tool's description) — a tool-level disclosure.
_EFFECTIVE_DESCRIPTION = (
    "coalesce(nullIf(toString(properties.$mcp_exec_tool_call_description), ''), "
    "toString(properties.$mcp_tool_description))"
)

# A per-row distinct-and-sorted list of resolved harness labels, collected from the
# token computed in the inner subquery. groupArray evaluates the label per row, so the
# token only has to be materialized once as `h`.
_HARNESS_LABELS_AGG = f"arraySort(arrayDistinct(groupArray({mcp_harness.harness_label_sql('h')})))"

# Raw failure-bucket parts of an errored $mcp_tool_call: the SDK stamps a semantic bucket
# ($mcp_error_type: internal, validation, api_4xx, api_5xx, permission, timeout, rate_limited,
# missing_context) plus an optional HTTP status ($mcp_error_status), falling back to "unknown"
# when neither is present (older SDKs / server paths that only set $mcp_is_error). Both
# properties are event-supplied and unbounded, so they are capped before grouping/filtering —
# an attacker emitting huge unique values must not inflate the grouping key or response size.
# The failures table groups on the raw parts and composes the display label from them, so the
# occurrences drill-down can requery a bucket by the same normalized parts without label parsing.
_RAW_ERROR_TYPE = "substring(coalesce(nullIf(toString(properties.$mcp_error_type), ''), 'unknown'), 1, 200)"
_RAW_ERROR_STATUS = "substring(coalesce(toString(properties.$mcp_error_status), ''), 1, 20)"
_COMPOSED_FAILURE_LABEL = "concat(error_type, if(empty(error_status), '', concat(' (HTTP ', error_status, ')')))"


def _display_properties(*, email: str, name: str) -> str:
    """JSON of only the person fields the Top-users cell renders, omitting blanks."""
    return json.dumps({k: v for k, v in (("email", email), ("name", name)) if v})


def _tool_call_where(tool: str, date_range: QueryDateRange, *, extra: list[ast.Expr] | None = None) -> ast.Expr:
    """WHERE for new-SDK $mcp_tool_call events scoped to one effective tool and window.

    `tool` is bound as an ast.Constant, never interpolated. `extra` appends
    query-specific predicates (e.g. notEmpty(description)).
    """
    exprs: list[ast.Expr] = [
        parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
        parse_expr("timestamp >= {date_from}", placeholders={"date_from": date_range.date_from_as_hogql()}),
        parse_expr("timestamp <= {date_to}", placeholders={"date_to": date_range.date_to_as_hogql()}),
        *tool_scope_exprs(tool),
    ]
    if extra:
        exprs.extend(extra)
    return ast.And(exprs=exprs)


class MCPToolTopUsersQueryRunner(AnalyticsQueryRunner[MCPToolTopUsersQueryResponse]):
    query: MCPToolTopUsersQuery
    cached_response: CachedMCPToolTopUsersQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def _where(self) -> ast.Expr:
        return _tool_call_where(self.query.toolName, self.query_date_range)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                distinct_id,
                argMax(person_email, timestamp) AS email,
                argMax(person_name, timestamp) AS name,
                count() AS calls,
                countIf(is_error) AS errors,
                round(countIf(is_error) * 100.0 / count(), 1) AS error_rate_pct,
                {_HARNESS_LABELS_AGG} AS harnesses,
                max(timestamp) AS last_seen
            FROM (
                SELECT
                    distinct_id,
                    timestamp,
                    toBool(properties.$mcp_is_error) AS is_error,
                    toString(person.properties.email) AS person_email,
                    toString(person.properties.name) AS person_name,
                    {token} AS h
                FROM events
                WHERE {where}
            )
            GROUP BY distinct_id
            ORDER BY calls DESC
            LIMIT 5
            """,
            placeholders={
                "_HARNESS_LABELS_AGG": parse_expr(_HARNESS_LABELS_AGG),
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
                # Only the fields the Top-users cell renders (display name + email), not the
                # whole person.properties blob — keeps the runner to least person-data exposure.
                person_properties=_display_properties(email=str(row[1] or ""), name=str(row[2] or "")),
                calls=int(row[3] or 0),
                errors=int(row[4] or 0),
                error_rate_pct=float(row[5] or 0),
                harnesses=[str(h) for h in (row[6] or [])],
                last_seen=str(row[7] or ""),
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
        # Failures share the tool-call source with every other tool-detail table, so they use the
        # effective tool name and the same $mcp_source scoping as the stats/error-rate query — the
        # two can never disagree. (Previously this read $exception events, which don't carry MCP
        # tool markers, so the table was always empty while the error rate showed failures.)
        return _tool_call_where(
            self.query.toolName,
            self.query_date_range,
            extra=[parse_expr("toBool(properties.$mcp_is_error)")],
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                {_COMPOSED_FAILURE_LABEL} AS message,
                error_type,
                error_status,
                count() AS occurrences,
                max(timestamp) AS last_seen,
                {_HARNESS_LABELS_AGG} AS harnesses
            FROM (
                SELECT
                    {_RAW_ERROR_TYPE} AS error_type,
                    {_RAW_ERROR_STATUS} AS error_status,
                    timestamp,
                    {token} AS h
                FROM events
                WHERE {where}
            )
            GROUP BY error_type, error_status
            ORDER BY occurrences DESC
            LIMIT 20
            """,
            placeholders={
                "_HARNESS_LABELS_AGG": parse_expr(_HARNESS_LABELS_AGG),
                "_COMPOSED_FAILURE_LABEL": parse_expr(_COMPOSED_FAILURE_LABEL),
                "_RAW_ERROR_TYPE": parse_expr(_RAW_ERROR_TYPE),
                "_RAW_ERROR_STATUS": parse_expr(_RAW_ERROR_STATUS),
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
                error_type=str(row[1] or ""),
                error_status=str(row[2] or ""),
                occurrences=int(row[3] or 0),
                last_seen=str(row[4] or ""),
                harnesses=[str(h) for h in (row[5] or [])],
            )
            for row in (response.results or [])
        ]
        return MCPToolFailuresQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


_CONVERSATION_ID = "coalesce(nullIf(toString(properties.$mcp_session_id), ''), toString(properties.$session_id))"

# Mirrors the capture-side MAX_ERROR_MESSAGE_LENGTH (services/mcp); event-supplied, so
# re-capped here in case a non-PostHog server emits an unbounded value.
_ERROR_MESSAGE = "substring(coalesce(toString(properties.$mcp_error_message), ''), 1, 2048)"


class MCPToolFailureOccurrencesQueryRunner(AnalyticsQueryRunner[MCPToolFailureOccurrencesQueryResponse]):
    query: MCPToolFailureOccurrencesQuery
    cached_response: CachedMCPToolFailureOccurrencesQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def _where(self) -> ast.Expr:
        # Bucket predicates normalize exactly like the failures table's grouping key, so a row
        # from that table always round-trips to its own occurrences. Values are bound as
        # ast.Constant, never interpolated.
        extra: list[ast.Expr] = [
            parse_expr("toBool(properties.$mcp_is_error)"),
            parse_expr(
                "{raw_type} = {error_type}",
                placeholders={
                    "raw_type": parse_expr(_RAW_ERROR_TYPE),
                    "error_type": ast.Constant(value=self.query.errorType),
                },
            ),
        ]
        if self.query.errorStatus:
            extra.append(
                parse_expr(
                    "{raw_status} = {error_status}",
                    placeholders={
                        "raw_status": parse_expr(_RAW_ERROR_STATUS),
                        "error_status": ast.Constant(value=self.query.errorStatus),
                    },
                )
            )
        else:
            extra.append(parse_expr("empty({raw_status})", placeholders={"raw_status": parse_expr(_RAW_ERROR_STATUS)}))
        return _tool_call_where(self.query.toolName, self.query_date_range, extra=extra)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                toString(timestamp) AS ts,
                distinct_id,
                session_id,
                {harness_label} AS harness,
                intent,
                error_message,
                error_status
            FROM (
                SELECT
                    timestamp,
                    distinct_id,
                    substring({_CONVERSATION_ID}, 1, 200) AS session_id,
                    if(toString(properties.$mcp_intent) = '{}', '', substring(toString(properties.$mcp_intent), 1, 1000)) AS intent,
                    {_ERROR_MESSAGE} AS error_message,
                    {_RAW_ERROR_STATUS} AS error_status,
                    {token} AS h
                FROM events
                WHERE {where}
            )
            ORDER BY ts DESC
            LIMIT 50
            """,
            placeholders={
                "harness_label": parse_expr(mcp_harness.harness_label_sql("h")),
                "_CONVERSATION_ID": parse_expr(_CONVERSATION_ID),
                "_ERROR_MESSAGE": parse_expr(_ERROR_MESSAGE),
                "_RAW_ERROR_STATUS": parse_expr(_RAW_ERROR_STATUS),
                "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                "where": self._where(),
            },
        )

    def _calculate(self) -> MCPToolFailureOccurrencesQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_failure_occurrences_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="mcp_tool_failure_occurrences_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolFailureOccurrenceItem(
                timestamp=str(row[0] or ""),
                distinct_id=str(row[1] or ""),
                session_id=str(row[2] or ""),
                harness=str(row[3] or ""),
                intent=str(row[4] or ""),
                error_message=str(row[5] or ""),
                error_status=str(row[6] or ""),
            )
            for row in (response.results or [])
        ]
        return MCPToolFailureOccurrencesQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


_IS_ERROR = "countIf(toBool(properties.$mcp_is_error))"
_P50 = "round(quantile(0.5)(toFloat(properties.$mcp_duration_ms)))"
_P95 = "round(quantile(0.95)(toFloat(properties.$mcp_duration_ms)))"


class MCPToolStatsQueryRunner(AnalyticsQueryRunner[MCPToolStatsQueryResponse]):
    query: MCPToolStatsQuery
    cached_response: CachedMCPToolStatsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                count() AS calls,
                {_IS_ERROR} AS errors,
                {_P50} AS p50_ms,
                {_P95} AS p95_ms,
                uniq(distinct_id) AS users,
                uniq({_CONVERSATION_ID}) AS conversations,
                countIf(notEmpty(toString(properties.$mcp_intent)) AND toString(properties.$mcp_intent) != '{}') AS with_intent
            FROM events
            WHERE {where}
            """,
            placeholders={
                "_CONVERSATION_ID": parse_expr(_CONVERSATION_ID),
                "_IS_ERROR": parse_expr(_IS_ERROR),
                "_P50": parse_expr(_P50),
                "_P95": parse_expr(_P95),
                "where": _tool_call_where(self.query.toolName, self.query_date_range),
            },
        )

    def _calculate(self) -> MCPToolStatsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_stats_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_tool_stats_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        row = (response.results or [None])[0]
        results = (
            [
                MCPToolStatsItem(
                    calls=int(row[0] or 0),
                    errors=int(row[1] or 0),
                    p50_ms=None if row[2] is None else float(row[2]),
                    p95_ms=None if row[3] is None else float(row[3]),
                    users=int(row[4] or 0),
                    conversations=int(row[5] or 0),
                    with_intent=int(row[6] or 0),
                )
            ]
            if row and int(row[0] or 0) > 0
            else []
        )
        return MCPToolStatsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


class MCPToolDailyStatsQueryRunner(AnalyticsQueryRunner[MCPToolDailyStatsQueryResponse]):
    query: MCPToolDailyStatsQuery
    cached_response: CachedMCPToolDailyStatsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Bucket granularity comes from the frontend's getDefaultInterval, so a sub-day window buckets
        # by hour/minute instead of collapsing to a single day point. dateTrunc respects the team
        # timezone, so the buckets line up with the frontend's gap-fill keys. Defaults to day.
        # Explicit generous LIMIT so a fine interval over a wide window (reachable via the interval
        # field, e.g. hourly over a quarter from an MCP caller) isn't silently cut to the default 100
        # rows — which, with ORDER BY day ASC, would drop the most recent buckets.
        interval = self.query.interval.value if self.query.interval else "day"
        return parse_select(
            """
            SELECT
                toString(dateTrunc({interval}, timestamp)) AS day,
                count() AS calls,
                {_IS_ERROR} AS errors,
                {_P50} AS p50,
                {_P95} AS p95,
                uniq(distinct_id) AS users,
                uniq({_CONVERSATION_ID}) AS sessions
            FROM events
            WHERE {where}
            GROUP BY day
            ORDER BY day
            LIMIT 10000
            """,
            placeholders={
                "interval": ast.Constant(value=interval),
                "_CONVERSATION_ID": parse_expr(_CONVERSATION_ID),
                "_IS_ERROR": parse_expr(_IS_ERROR),
                "_P50": parse_expr(_P50),
                "_P95": parse_expr(_P95),
                "where": _tool_call_where(self.query.toolName, self.query_date_range),
            },
        )

    def _calculate(self) -> MCPToolDailyStatsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_daily_stats_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_tool_daily_stats_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolDailyStatItem(
                day=str(row[0] or ""),
                calls=int(row[1] or 0),
                errors=int(row[2] or 0),
                p50=float(row[3] or 0),
                p95=float(row[4] or 0),
                users=int(row[5] or 0),
                sessions=int(row[6] or 0),
            )
            for row in (response.results or [])
        ]
        return MCPToolDailyStatsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


class MCPToolDescriptionsQueryRunner(AnalyticsQueryRunner[MCPToolDescriptionsQueryResponse]):
    query: MCPToolDescriptionsQuery
    cached_response: CachedMCPToolDescriptionsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        where = _tool_call_where(
            self.query.toolName,
            self.query_date_range,
            extra=[
                parse_expr("notEmpty({description})", placeholders={"description": parse_expr(_EFFECTIVE_DESCRIPTION)})
            ],
        )
        return parse_select(
            """
            SELECT
                {_EFFECTIVE_DESCRIPTION} AS description,
                toString(max(timestamp)) AS last_seen
            FROM events
            WHERE {where}
            GROUP BY description
            ORDER BY last_seen DESC
            LIMIT 5
            """,
            placeholders={"_EFFECTIVE_DESCRIPTION": parse_expr(_EFFECTIVE_DESCRIPTION), "where": where},
        )

    def _calculate(self) -> MCPToolDescriptionsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_descriptions_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_tool_descriptions_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolDescriptionItem(description=str(row[0] or ""), last_seen=str(row[1] or ""))
            for row in (response.results or [])
        ]
        return MCPToolDescriptionsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


class MCPToolSampleIntentsQueryRunner(AnalyticsQueryRunner[MCPToolSampleIntentsQueryResponse]):
    query: MCPToolSampleIntentsQuery
    cached_response: CachedMCPToolSampleIntentsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        where = _tool_call_where(
            self.query.toolName,
            self.query_date_range,
            extra=[
                parse_expr("notEmpty(toString(properties.$mcp_intent))"),
                parse_expr("toString(properties.$mcp_intent) != '{}'"),
            ],
        )
        return parse_select(
            """
            SELECT
                toString(timestamp) AS timestamp,
                intent,
                intent_source,
                {harness_label} AS harness
            FROM (
                SELECT
                    timestamp,
                    toString(properties.$mcp_intent) AS intent,
                    toString(properties.$mcp_intent_source) AS intent_source,
                    {token} AS h
                FROM events
                WHERE {where}
            )
            ORDER BY timestamp DESC
            LIMIT 5
            """,
            placeholders={
                "harness_label": parse_expr(mcp_harness.harness_label_sql("h")),
                "token": parse_expr(mcp_harness.HARNESS_TOKEN_SQL),
                "where": where,
            },
        )

    def _calculate(self) -> MCPToolSampleIntentsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_sample_intents_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_tool_sample_intents_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolSampleIntentItem(
                timestamp=str(row[0] or ""),
                intent=str(row[1] or ""),
                intent_source=str(row[2] or ""),
                harness=str(row[3] or ""),
            )
            for row in (response.results or [])
        ]
        return MCPToolSampleIntentsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )


_WINDOW_FN: dict[NeighborDirection, str] = {
    NeighborDirection.BEFORE: "lagInFrame",
    NeighborDirection.AFTER: "leadInFrame",
}


class MCPToolNeighborsQueryRunner(AnalyticsQueryRunner[MCPToolNeighborsQueryResponse]):
    query: MCPToolNeighborsQuery
    cached_response: CachedMCPToolNeighborsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return mcp_query_date_range(self.team, self.query.dateRange)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # The CTE collects every tool call in qualifying conversations (not just the target
        # tool) so the window function can see each call's neighbour; the target tool is
        # selected in the outer WHERE. window_fn is chosen from a fixed map, never input.
        window_fn = _WINDOW_FN[self.query.neighborDirection]
        # Built from a fixed function name + hardcoded window, never user input; passed to
        # parse_expr as a variable (not a literal f-string) so hogql-fstring-audit stays clean.
        neighbor_expr = (
            f"{window_fn}(tool) OVER ("
            "PARTITION BY conv_id ORDER BY timestamp "
            "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)"
        )
        cte_where = ast.And(
            exprs=[
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=MCP_TOOL_CALL_EVENT)}),
                parse_expr(
                    "timestamp >= {date_from}", placeholders={"date_from": self.query_date_range.date_from_as_hogql()}
                ),
                parse_expr(
                    "timestamp <= {date_to}", placeholders={"date_to": self.query_date_range.date_to_as_hogql()}
                ),
                parse_expr(
                    "properties.$mcp_source = {source}", placeholders={"source": ast.Constant(value=NEW_SDK_SOURCE)}
                ),
                parse_expr("notEmpty({conv_id})", placeholders={"conv_id": parse_expr(_CONVERSATION_ID)}),
            ]
        )
        return parse_select(
            """
            WITH tool_calls AS (
                SELECT
                    {_CONVERSATION_ID} AS conv_id,
                    timestamp,
                    {effective_tool} AS tool
                FROM events
                WHERE {cte_where}
            )
            SELECT neighbor_tool, count() AS co_occurrences
            FROM (
                SELECT
                    tool,
                    {neighbor_expr} AS neighbor_tool
                FROM tool_calls
            )
            WHERE tool = {tool} AND neighbor_tool IS NOT NULL AND neighbor_tool != '' AND neighbor_tool != tool
            GROUP BY neighbor_tool
            ORDER BY co_occurrences DESC
            LIMIT 5
            """,
            placeholders={
                "_CONVERSATION_ID": parse_expr(_CONVERSATION_ID),
                "effective_tool": parse_expr(EFFECTIVE_TOOL_SQL),
                "neighbor_expr": parse_expr(neighbor_expr),
                "cte_where": cte_where,
                "tool": ast.Constant(value=self.query.toolName),
            },
        )

    def _calculate(self) -> MCPToolNeighborsQueryResponse:
        with tags_context(
            product=Product.MCP_ANALYTICS,
            feature=Feature.QUERY,
            team_id=self.team.id,
            name="mcp_tool_neighbors_query",
        ):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="mcp_tool_neighbors_query",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = [
            MCPToolNeighborItem(neighbor_tool=str(row[0] or ""), co_occurrences=int(row[1] or 0))
            for row in (response.results or [])
        ]
        return MCPToolNeighborsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
