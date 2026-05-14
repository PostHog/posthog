import datetime as dt

from django.db.models import QuerySet

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person import Person
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPSession

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


def list_submissions(team: Team, kind: enums.SubmissionKind) -> QuerySet[MCPAnalyticsSubmission]:
    return MCPAnalyticsSubmission.objects.filter(team=team, kind=kind).order_by("-created_at")


def list_mcp_sessions(team: Team, limit: int, offset: int) -> list[contracts.MCPSession]:
    """Read the denormalized session metadata that the Temporal backfill maintains.

    Person email/name are resolved on the fly by joining MCPSession.distinct_id to
    the Person model (routed through personhog), matching how SessionRecording
    handles it. event_count is approximated by the size of tools_used since the
    new table does not carry a per-call counter.
    """
    rows = list(MCPSession.objects.filter(team=team).order_by("-session_end")[offset : offset + limit])
    persons_by_distinct_id = _resolve_persons(team.id, rows)
    return [_to_session_contract(row, persons_by_distinct_id) for row in rows]


def _resolve_persons(team_id: int, rows: list[MCPSession]) -> dict[str, Person]:
    distinct_ids = list({row.distinct_id for row in rows if row.distinct_id})
    if not distinct_ids:
        return {}
    return get_persons_mapped_by_distinct_id(team_id, distinct_ids)


def _person_display(person: Person | None) -> dict[str, str]:
    if person is None:
        return {"email": "", "name": ""}
    props = person.properties or {}
    return {
        "email": str(props.get("email") or ""),
        "name": str(props.get("name") or ""),
    }


def _to_session_contract(row: MCPSession, persons_by_distinct_id: dict[str, Person]) -> contracts.MCPSession:
    person_display = _person_display(persons_by_distinct_id.get(row.distinct_id))
    tools_used = list(row.tools_used or [])
    return contracts.MCPSession(
        session_id=row.session_id,
        tool_calls=row.tool_call_count,
        session_start=row.session_start,
        session_end=row.session_end,
        distinct_id_count=0,
        tools_used=tools_used,
        mcp_client_name=row.mcp_client_name or "",
        distinct_id=row.distinct_id or "",
        person_email=person_display["email"],
        person_name=person_display["name"],
        intent=row.intent or "",
    )


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
