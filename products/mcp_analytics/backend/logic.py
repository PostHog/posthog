from datetime import timedelta
from typing import Any

from django.db.models import CharField, F, Func, Q, QuerySet, Value
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person import Person
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPIntentClusterSnapshot, MCPSession

MCP_TOOL_CALL_EVENT = "mcp_tool_call"

# How long a snapshot may sit in COMPUTING before we assume the task died and
# auto-recover. Generous because a real recompute completes in well under a
# minute even at the top_n=500 cap; anything past 10 minutes is a dead task.
STALE_COMPUTING_THRESHOLD = timedelta(minutes=10)

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
    AND properties.$mcp_conversation_id = {session_id}
ORDER BY timestamp ASC
LIMIT 500
"""


def list_submissions(team: Team, kind: enums.SubmissionKind) -> QuerySet[MCPAnalyticsSubmission]:
    return MCPAnalyticsSubmission.objects.filter(team=team, kind=kind).order_by("-created_at")


SESSION_SORT_FIELDS: frozenset[str] = frozenset(
    {
        "session_id",
        "session_start",
        "session_end",
        "duration_seconds",
        "tool_call_count",
        "mcp_client_name",
        "distinct_id",
    }
)
DEFAULT_SESSION_ORDER_BY = "-session_end"


def _normalise_order_by(order_by: str) -> str:
    """Validate and normalise the order_by query param.

    Accepts a single column with an optional leading '-' for descending. Falls
    back to the default if the field isn't whitelisted; we don't want a stray
    query param to ORDER BY an arbitrary column.
    """
    raw = (order_by or "").strip()
    if not raw:
        return DEFAULT_SESSION_ORDER_BY
    descending = raw.startswith("-")
    field = raw.lstrip("-")
    if field not in SESSION_SORT_FIELDS:
        return DEFAULT_SESSION_ORDER_BY
    return f"-{field}" if descending else field


def list_mcp_sessions(
    team: Team,
    limit: int,
    offset: int,
    search: str = "",
    order_by: str = "",
) -> list[contracts.MCPSession]:
    """Read the denormalized session metadata that the Temporal backfill maintains.

    Person email/name are resolved on the fly by joining MCPSession.distinct_id to
    the Person model (routed through personhog), matching how SessionRecording
    handles it. event_count is approximated by the size of tools_used since the
    new table does not carry a per-call counter.

    ``search`` does case-insensitive substring matching across session_id,
    distinct_id, mcp_client_name, and any element of tools_used.

    ``order_by`` is a whitelisted column name; prefix with '-' for descending.
    """
    queryset: QuerySet[MCPSession] = MCPSession.objects.filter(team=team)
    term = search.strip()
    if term:
        # tools_used is a Postgres array; flatten it to a single string so a single
        # ILIKE catches the substring match across all tool names.
        queryset = queryset.annotate(
            _tools_used_text=Func(
                F("tools_used"),
                Value(" "),
                function="array_to_string",
                output_field=CharField(),
            )
        ).filter(
            Q(session_id__icontains=term)
            | Q(distinct_id__icontains=term)
            | Q(mcp_client_name__icontains=term)
            | Q(_tools_used_text__icontains=term)
        )
    rows = list(queryset.order_by(_normalise_order_by(order_by))[offset : offset + limit])
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

    Defensive side effect: any row stuck in COMPUTING past
    STALE_COMPUTING_THRESHOLD is auto-flipped to ERROR so the UI can offer
    a retry. The Celery task may have died between writing COMPUTING and
    writing its final status (worker restart, OOM, etc.) and otherwise has
    no path back to a usable state.
    """
    MCPIntentClusterSnapshot.objects.filter(
        team=team,
        status=MCPIntentClusterSnapshot.Status.COMPUTING,
        updated_at__lt=timezone.now() - STALE_COMPUTING_THRESHOLD,
    ).update(
        status=MCPIntentClusterSnapshot.Status.ERROR,
        error_message="Recompute task did not complete within the expected window. Retry to try again.",
    )

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
    journey_raw = item.get("journey")
    return contracts.IntentCluster(
        id=int(item.get("id", 0)),
        label=str(item.get("label", "")),
        intent_count=int(item.get("intent_count", 0)),
        session_count=int(item.get("session_count", 0)),
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
        journey=_to_journey_dto(journey_raw) if isinstance(journey_raw, dict) else None,
    )


def _to_journey_path_dto(path: dict[str, Any]) -> contracts.IntentClusterJourneyPath:
    return contracts.IntentClusterJourneyPath(
        steps=[str(s) if s is not None else None for s in path.get("steps", [])],
        outcome=str(path.get("outcome", "completed")),
        count=int(path.get("count", 0)),
    )


def _to_journey_dto(journey: dict[str, Any]) -> contracts.IntentClusterJourney:
    return contracts.IntentClusterJourney(
        paths=[_to_journey_path_dto(p) for p in journey.get("paths", []) if isinstance(p, dict)],
        total_sessions=int(journey.get("total_sessions", 0)),
        leak=(_to_journey_path_dto(journey["leak"]) if isinstance(journey.get("leak"), dict) else None),
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
