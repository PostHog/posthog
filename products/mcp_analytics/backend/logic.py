import datetime as dt
from typing import Any

from django.db.models import QuerySet

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

MCP_TOOL_CALL_EVENT = "mcp_tool_call"

# Bound every sessions/tool-calls query to a fixed lookback so a single page
# load can't trigger a full-history scan of `events` on the shared ClickHouse
# cluster. Tune this when real customer traffic exposes a need for longer windows.
MCP_SESSIONS_DEFAULT_LOOKBACK_DAYS = 30
MCP_TOOL_CALLS_RESULT_LIMIT = 500

_MCP_TOOL_CALLS_SQL = """
SELECT
    uuid AS event_id,
    timestamp,
    toString(properties.$mcp_tool_name) AS tool_name,
    toString(properties.$mcp_intent) AS intent,
    toString(properties.$mcp_is_error) AS is_error_raw,
    toString(properties.$mcp_error_message) AS error_message,
    toString(properties.$mcp_duration_ms) AS duration_ms_raw
FROM events
WHERE event = {event}
    AND properties.$session_id = {session_id}
    AND timestamp >= {date_from}
    AND timestamp <= {date_to}
ORDER BY timestamp ASC
LIMIT {limit}
"""

_MCP_SESSIONS_SQL = """
SELECT
    properties.$session_id AS session_id,
    count() AS event_count,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen,
    count(DISTINCT distinct_id) AS distinct_id_count,
    arrayDistinct(groupArray(properties.$mcp_tool_name)) AS tools_used,
    argMax(properties.$mcp_client_name, timestamp) AS mcp_client_name,
    argMax(person_id, timestamp) AS person_id,
    argMax(toString(person.properties.email), timestamp) AS person_email,
    argMax(toString(person.properties.name), timestamp) AS person_name,
    argMax(distinct_id, timestamp) AS last_distinct_id
FROM events
WHERE event = {event}
    AND timestamp >= {date_from}
    AND properties.$session_id IS NOT NULL
    AND properties.$session_id != ''
GROUP BY session_id
ORDER BY last_seen DESC
LIMIT {limit}
OFFSET {offset}
"""


def list_submissions(team: Team, kind: enums.SubmissionKind) -> QuerySet[MCPAnalyticsSubmission]:
    return MCPAnalyticsSubmission.objects.filter(team=team, kind=kind).order_by("-created_at")


def list_mcp_sessions(team: Team, limit: int, offset: int) -> list[contracts.MCPSession]:
    date_from = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=MCP_SESSIONS_DEFAULT_LOOKBACK_DAYS)
    query = parse_select(
        _MCP_SESSIONS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "date_from": ast.Constant(value=date_from),
            "limit": ast.Constant(value=limit),
            "offset": ast.Constant(value=offset),
        },
    )
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        response = execute_hogql_query(query=query, team=team)
    return [
        contracts.MCPSession(
            session_id=row[0] or "",
            event_count=int(row[1] or 0),
            first_seen=row[2],
            last_seen=row[3],
            distinct_id_count=int(row[4] or 0),
            tools_used=[tool for tool in (row[5] or []) if tool],
            mcp_client_name=row[6] or "",
            person_id=_clean_person_id(row[7]),
            person_email=_clean_person_property(row[8]),
            person_name=_clean_person_property(row[9]),
            distinct_id=row[10] or "",
        )
        for row in (response.results or [])
    ]


_ANONYMOUS_PERSON_ID = "00000000-0000-0000-0000-000000000000"


def _clean_person_id(value: Any) -> str:
    if value is None:
        return ""
    value_str = str(value)
    return "" if value_str == _ANONYMOUS_PERSON_ID else value_str


def _clean_person_property(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    # HogQL returns the literal string 'null' when the property is missing
    return "" if text in ("", "null") else text


def list_mcp_tool_calls(
    team: Team,
    session_id: str,
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
) -> contracts.MCPToolCallList:
    # Default to the same lookback the sessions list uses so we never have a session
    # in the list whose tool-calls fall outside the window. Callers (the frontend
    # session-detail view) can pin a tighter range using the parent session's
    # first_seen / last_seen timestamps.
    if date_from is None:
        date_from = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=MCP_SESSIONS_DEFAULT_LOOKBACK_DAYS)
    if date_to is None:
        date_to = dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=1)
    # Fetch one extra row so we can detect (and surface) silent truncation.
    fetch_limit = MCP_TOOL_CALLS_RESULT_LIMIT + 1
    query = parse_select(
        _MCP_TOOL_CALLS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "session_id": ast.Constant(value=session_id),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "limit": ast.Constant(value=fetch_limit),
        },
    )
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        response = execute_hogql_query(query=query, team=team)
    rows = response.results or []
    truncated = len(rows) > MCP_TOOL_CALLS_RESULT_LIMIT
    rows = rows[:MCP_TOOL_CALLS_RESULT_LIMIT]
    return contracts.MCPToolCallList(
        tool_calls=[
            contracts.MCPToolCall(
                event_id=str(row[0]) if row[0] else "",
                timestamp=row[1],
                tool_name=row[2] or "",
                intent=row[3] or "",
                is_error=str(row[4]).lower() in ("true", "1"),
                error_message=row[5] or "",
                duration_ms=_parse_int(row[6]),
            )
            for row in rows
        ],
        truncated=truncated,
    )


def _parse_int(value: str | int | None) -> int | None:
    if value is None or value == "" or value == "null":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def create_feedback_submission(
    team: Team, created_by: User | None, submission: contracts.CreateFeedbackSubmission
) -> MCPAnalyticsSubmission:
    return MCPAnalyticsSubmission.objects.create(
        team=team,
        created_by=created_by,
        kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
        goal=submission.goal,
        summary=submission.feedback,
        category=submission.category,
        attempted_tool=submission.context.attempted_tool,
        mcp_client_name=submission.context.mcp_client_name,
        mcp_client_version=submission.context.mcp_client_version,
        mcp_protocol_version=submission.context.mcp_protocol_version,
        mcp_transport=submission.context.mcp_transport,
        mcp_session_id=submission.context.mcp_session_id,
        mcp_trace_id=submission.context.mcp_trace_id,
    )


def create_missing_capability_submission(
    team: Team, created_by: User | None, submission: contracts.CreateMissingCapabilitySubmission
) -> MCPAnalyticsSubmission:
    return MCPAnalyticsSubmission.objects.create(
        team=team,
        created_by=created_by,
        kind=MCPAnalyticsSubmission.Kind.MISSING_CAPABILITY,
        goal=submission.goal,
        summary=submission.missing_capability,
        blocked=submission.blocked,
        attempted_tool=submission.context.attempted_tool,
        mcp_client_name=submission.context.mcp_client_name,
        mcp_client_version=submission.context.mcp_client_version,
        mcp_protocol_version=submission.context.mcp_protocol_version,
        mcp_transport=submission.context.mcp_transport,
        mcp_session_id=submission.context.mcp_session_id,
        mcp_trace_id=submission.context.mcp_trace_id,
    )
