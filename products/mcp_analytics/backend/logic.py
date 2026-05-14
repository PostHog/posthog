from typing import Any

from django.db.models import QuerySet

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPIntentClusterSnapshot

MCP_TOOL_CALL_EVENT = "mcp_tool_call"

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
ORDER BY timestamp ASC
LIMIT 500
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


def list_mcp_tool_calls(team: Team, session_id: str) -> list[contracts.MCPToolCall]:
    query = parse_select(
        _MCP_TOOL_CALLS_SQL,
        placeholders={
            "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
            "session_id": ast.Constant(value=session_id),
        },
    )
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        response = execute_hogql_query(query=query, team=team)
    return [
        contracts.MCPToolCall(
            event_id=str(row[0]) if row[0] else "",
            timestamp=row[1],
            tool_name=row[2] or "",
            intent=row[3] or "",
            is_error=str(row[4]).lower() in ("true", "1"),
            error_message=row[5] or "",
            duration_ms=_parse_int(row[6]),
        )
        for row in (response.results or [])
    ]


def _parse_int(value: str | int | None) -> int | None:
    if value is None or value == "" or value == "null":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_intent_cluster_snapshot(team: Team) -> contracts.IntentClusterSnapshot:
    """Return the current intent cluster snapshot for a team.

    When no snapshot exists yet, returns an empty IDLE one so callers can
    render the "compute" CTA without distinguishing "missing" from "empty".
    """
    snapshot = MCPIntentClusterSnapshot.objects.filter(team=team).select_related("last_computed_by").first()
    if snapshot is None:
        return contracts.IntentClusterSnapshot(
            status=MCPIntentClusterSnapshot.Status.IDLE,
            error_message="",
            last_computed_at=None,
            last_computed_by_email="",
            clusters=[],
            computed_with=None,
        )

    blob = snapshot.clusters or {}
    clusters_raw = blob.get("clusters", []) if isinstance(blob, dict) else []
    meta_raw = blob.get("computed_with") if isinstance(blob, dict) else None

    return contracts.IntentClusterSnapshot(
        status=snapshot.status,
        error_message=snapshot.error_message,
        last_computed_at=snapshot.last_computed_at,
        last_computed_by_email=snapshot.last_computed_by.email if snapshot.last_computed_by else "",
        clusters=[_to_cluster_dto(item) for item in clusters_raw if isinstance(item, dict)],
        computed_with=_to_meta_dto(meta_raw) if isinstance(meta_raw, dict) else None,
    )


def _to_cluster_dto(item: dict[str, Any]) -> contracts.IntentCluster:
    return contracts.IntentCluster(
        id=int(item.get("id", 0)),
        label=str(item.get("label", "")),
        intent_count=int(item.get("intent_count", 0)),
        call_count=int(item.get("call_count", 0)),
        error_count=int(item.get("error_count", 0)),
        error_rate_pct=float(item.get("error_rate_pct", 0.0)),
        routing_entropy=float(item.get("routing_entropy", 0.0)),
        tool_distribution=[
            contracts.IntentClusterToolEntry(
                tool=str(entry.get("tool", "")),
                count=int(entry.get("count", 0)),
                pct=float(entry.get("pct", 0.0)),
                errors=int(entry.get("errors", 0)),
                error_rate_pct=float(entry.get("error_rate_pct", 0.0)),
            )
            for entry in item.get("tool_distribution", [])
            if isinstance(entry, dict)
        ],
        sample_intents=[str(s) for s in item.get("sample_intents", []) if isinstance(s, str)],
    )


def _to_meta_dto(meta: dict[str, Any]) -> contracts.IntentClusterSnapshotMeta:
    return contracts.IntentClusterSnapshotMeta(
        distance_threshold=float(meta.get("distance_threshold", 0.0)),
        embedding_model=str(meta.get("embedding_model", "")),
        n_intents=int(meta.get("n_intents", 0)),
        n_clusters=int(meta.get("n_clusters", 0)),
    )


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
