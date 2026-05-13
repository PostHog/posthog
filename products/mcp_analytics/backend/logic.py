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

_MCP_SESSIONS_SQL = """
SELECT
    properties.$session_id AS session_id,
    count() AS event_count,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen,
    count(DISTINCT distinct_id) AS distinct_id_count,
    arrayDistinct(groupArray(properties.$mcp_tool_name)) AS tools_used,
    argMax(properties.$mcp_client_name, timestamp) AS mcp_client_name
FROM events
WHERE event = {event}
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
    query = parse_select(
        _MCP_SESSIONS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
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
        )
        for row in (response.results or [])
    ]


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
