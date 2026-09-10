from datetime import datetime

from django.db import transaction
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.api.capture import capture_internal
from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_analytics.backend import logic
from products.mcp_analytics.backend.hogql_queries.base import (
    EFFECTIVE_DESCRIPTION_SQL,
    EFFECTIVE_TOOL_SQL,
    NEW_SDK_SOURCE,
)
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

from . import contracts
from .constants import MCP_MISSING_CAPABILITY_EVENT
from .enums import SubmissionKind


def _to_submission(instance: MCPAnalyticsSubmission) -> contracts.Submission:
    return contracts.Submission(
        id=instance.id,
        kind=SubmissionKind(instance.kind),
        goal=instance.goal,
        summary=instance.summary,
        category=instance.category,
        blocked=instance.blocked,
        attempted_tool=instance.attempted_tool,
        mcp_client_name=instance.mcp_client_name,
        mcp_client_version=instance.mcp_client_version,
        mcp_protocol_version=instance.mcp_protocol_version,
        mcp_transport=instance.mcp_transport,
        mcp_session_id=instance.mcp_session_id,
        mcp_trace_id=instance.mcp_trace_id,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


def list_feedback_submissions(team: Team) -> list[contracts.Submission]:
    return [_to_submission(instance) for instance in logic.list_submissions(team, SubmissionKind.FEEDBACK)]


def list_missing_capability_submissions(team: Team) -> list[contracts.Submission]:
    return [_to_submission(instance) for instance in logic.list_submissions(team, SubmissionKind.MISSING_CAPABILITY)]


def create_feedback_submission(
    team: Team, created_by: User | None, submission: contracts.CreateFeedbackSubmission
) -> contracts.Submission:
    return _to_submission(logic.create_feedback_submission(team, created_by, submission))


def create_missing_capability_submission(
    team: Team, created_by: User | None, submission: contracts.CreateMissingCapabilitySubmission
) -> contracts.Submission:
    return _to_submission(logic.create_missing_capability_submission(team, created_by, submission))


def capture_missing_capability_event(team: Team, distinct_id: str, submission: contracts.Submission) -> None:
    properties: dict[str, object] = {
        "submission_id": str(submission.id),
        "kind": submission.kind,
        "attempted_tool_present": bool(submission.attempted_tool),
        "mcp_client_name_present": bool(submission.mcp_client_name),
        "mcp_session_id_present": bool(submission.mcp_session_id),
        "mcp_trace_id_present": bool(submission.mcp_trace_id),
        "$mcp_source": "posthog_mcp_analytics",
        "$mcp_tool_name": "mcp-missing-capability-report",
        "missing_capability_blocked": submission.blocked,
    }
    if submission.mcp_session_id:
        properties["$mcp_session_id"] = submission.mcp_session_id
    if submission.mcp_trace_id:
        properties["$mcp_trace_id"] = submission.mcp_trace_id

    capture_internal(
        token=team.api_token,
        event_name=MCP_MISSING_CAPABILITY_EVENT,
        event_source="mcp_analytics_missing_capability",
        distinct_id=distinct_id,
        properties=properties,
        event_uuid=str(submission.id),
        process_person_profile=False,
    )


def list_mcp_sessions(
    team: Team,
    limit: int,
    offset: int,
    search: str = "",
    order_by: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
) -> contracts.MCPSessionsPage:
    return logic.list_mcp_sessions(
        team, limit=limit, offset=offset, search=search, order_by=order_by, date_from=date_from, date_to=date_to
    )


def list_mcp_tool_calls(
    team: Team,
    session_id: str,
    limit: int,
    offset: int,
    date_from: datetime | None = None,
) -> contracts.MCPToolCallsPage:
    return logic.list_mcp_tool_calls(team, session_id=session_id, limit=limit, offset=offset, date_from=date_from)


def generate_session_intent(team: Team, session_id: str, date_from: datetime | None = None) -> str:
    """Generate (or return the cached) intent summary for an MCP session.

    Shared entry point for the UI's on-demand button and any future caller
    (e.g. clustering). Persists the result to ``MCPSession.intent``. ``date_from``
    bounds the event scan to keep older sessions summarisable (same bound as
    ``list_mcp_tool_calls``).
    """
    return logic.generate_session_intent(team, session_id=session_id, date_from=date_from)


def generate_intent_digest(team: Team) -> contracts.IntentDigest:
    """Generate (or return the cached) project-level digest of what agents are trying to do.

    Powers the dashboard's activity tab: a one-sentence summary plus semantic themes. Cached
    both by intent corpus and by recency, so a quiet project regenerates only when its intents
    change and a busy one regenerates at a bounded rate.
    """
    return logic.generate_intent_digest(team)


def get_activity_overview(team: Team) -> contracts.ActivityOverview:
    """Compute the activity view's aggregates and recent-call feed in one pass.

    Bounded to the last 30 days; always computed fresh (the view polls to watch
    data arrive).
    """
    return logic.get_activity_overview(team)


def get_intent_cluster_snapshot(team: Team, tool: str | None = None) -> contracts.IntentClusterSnapshot:
    """The latest snapshot, optionally narrowed to one tool's slice of it."""
    return logic.get_intent_cluster_snapshot(team, tool=tool)


def trigger_intent_cluster_recompute(team: Team, user: User | None) -> None:
    """Kick off the intent cluster recompute Temporal workflow.

    Returns immediately. Use ``get_intent_cluster_snapshot`` to poll status —
    the workflow's compute activity writes the snapshot status (COMPUTING →
    IDLE/ERROR) as it runs.
    """
    import asyncio

    from django.conf import settings

    from temporalio.exceptions import WorkflowAlreadyStartedError

    from posthog.temporal.common.client import async_connect
    from posthog.temporal.mcp_analytics.intent_clustering.constants import (
        CHILD_WORKFLOW_ID_PREFIX,
        WORKFLOW_EXECUTION_TIMEOUT,
        WORKFLOW_NAME,
    )
    from posthog.temporal.mcp_analytics.intent_clustering.models import IntentClusteringWorkflowInputs

    from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot

    # One run at a time per team: while a fresh run holds the snapshot in
    # COMPUTING, another dispatch would only stack a duplicate workflow on the
    # queue behind it. A run stuck past STALE_COMPUTING_THRESHOLD is presumed
    # dead (same rule as the sweep in get_intent_cluster_snapshot), so a
    # retry is allowed through. The row lock serialises concurrent triggers so
    # they can't all pass the freshness check before any of them claims the
    # snapshot; the Temporal dispatch stays outside the transaction.
    # Claiming COMPUTING before dispatching also means the 202 response and
    # any immediate poll see consistent state — the workflow's activity
    # re-asserts COMPUTING on pickup, and both writes are idempotent.
    with transaction.atomic():
        snapshot, created = MCPIntentClusterSnapshot.objects.select_for_update().get_or_create(
            team=team,
            defaults={
                "status": MCPIntentClusterSnapshot.Status.COMPUTING,
                "error_message": "",
                "last_computed_by": user,
            },
        )
        if not created:
            if (
                snapshot.status == MCPIntentClusterSnapshot.Status.COMPUTING
                and snapshot.updated_at >= timezone.now() - logic.STALE_COMPUTING_THRESHOLD
            ):
                return
            snapshot.status = MCPIntentClusterSnapshot.Status.COMPUTING
            snapshot.error_message = ""
            snapshot.last_computed_by = user
            snapshot.save(update_fields=["status", "error_message", "last_computed_by", "updated_at"])

    # Deterministic per team: Temporal refuses a second start while a run with
    # this id is live, so even a run that outlives STALE_COMPUTING_THRESHOLD
    # (which is shorter than the 20-minute execution timeout) can't be
    # overlapped by a retry — the id frees up once the previous run closes.
    workflow_id = f"{CHILD_WORKFLOW_ID_PREFIX}-{team.id}-adhoc"

    # Create + use the Temporal client inside one event loop. sync_connect()
    # would build the client in asgiref's managed loop and then asyncio.run()
    # would call start_workflow in a different loop; the temporalio Rust
    # bridge is currently loop-agnostic but the inconsistency is fragile.
    # Matches the cluster_mcp_intents management command pattern.
    async def _start() -> None:
        client = await async_connect()
        # execution_timeout bounds the whole run *including* queue wait: with
        # no worker polling the task queue, an unbounded workflow sits pending
        # forever and every recompute click stacks another one behind it.
        await client.start_workflow(
            WORKFLOW_NAME,
            IntentClusteringWorkflowInputs(team_id=team.id, user_id=user.id if user else None),
            id=workflow_id,
            task_queue=settings.MCPA_TASK_QUEUE,
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
        )

    try:
        asyncio.run(_start())
    except WorkflowAlreadyStartedError:
        # The previous run outlived the stale threshold but is genuinely still
        # running — leave the snapshot in COMPUTING; the live run flips the
        # status when it finishes.
        return
    except Exception:
        # Dispatch failed, so no activity will ever flip the status — revert
        # the optimistic COMPUTING write instead of leaving the snapshot stuck
        # until the stale-COMPUTING sweep in get_intent_cluster_snapshot.
        MCPIntentClusterSnapshot.objects.filter(team=team).update(
            status=MCPIntentClusterSnapshot.Status.ERROR,
            error_message="Failed to start the intent clustering workflow",
            updated_at=timezone.now(),
        )
        raise


# ---------------------------------------------------------------------------
# Measured-server aggregation surface (consumed by mcp_registry).
#
# mcp_registry's measured-server pipeline aggregates one project's new-SDK
# $mcp_tool_call events into per-server and per-tool stats. It needs the same
# exec-coalescing rules this product's own query runners use, so single-exec
# servers don't collapse into one `exec` bucket. Those rules live in
# hogql_queries/base; these helpers return them as parsed HogQL placeholders
# (and a HogQL fragment for the one cross-team discovery question) so the
# consumer never handles raw SQL text.
# ---------------------------------------------------------------------------

_SERVER_STATS_SELECT = """
    SELECT
        toString(properties.$mcp_server_name) AS server_name,
        count() AS calls,
        uniq(toString(properties.$mcp_session_id)) AS sessions,
        countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS errors,
        countIf(notEmpty(toString(properties.$mcp_intent))) AS calls_with_intent,
        uniq({effective_tool}) AS distinct_tools,
        uniq(toString(properties.$mcp_client_name)) AS client_names
    FROM events
    WHERE event = '$mcp_tool_call'
        AND timestamp >= {date_from}
        AND properties.$mcp_source = {source}
        AND notEmpty(toString(properties.$mcp_server_name))
    GROUP BY server_name
    ORDER BY calls DESC
"""

_TOOL_STATS_SELECT = """
    SELECT
        {effective_tool} AS tool_name,
        any({effective_description}) AS description,
        count() AS calls,
        countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS errors
    FROM events
    WHERE event = '$mcp_tool_call'
        AND timestamp >= {date_from}
        AND properties.$mcp_source = {source}
        AND toString(properties.$mcp_server_name) = {server_name}
        AND notEmpty({effective_tool})
    GROUP BY tool_name
    ORDER BY calls DESC
    LIMIT {tool_limit}
"""

# Only the deploy-configured database name is interpolated, never caller input.
_DISCOVERY_SQL = """
    SELECT DISTINCT team_id
    FROM {database}.events
    WHERE event = '$mcp_tool_call'
        AND timestamp >= now() - INTERVAL %(window_days)s DAY
        AND JSONExtractString(properties, '$mcp_source') = %(source)s
    ORDER BY team_id
    LIMIT %(limit)s
"""


def measured_server_stats_select() -> str:
    """HogQL select for per-server measured aggregates. Placeholders: date_from, source."""
    return _SERVER_STATS_SELECT


def measured_tool_stats_select() -> str:
    """HogQL select for per-tool measured aggregates. Placeholders: date_from, source, server_name, tool_limit."""
    return _TOOL_STATS_SELECT


def measured_discovery_sql(database: str) -> str:
    """ClickHouse SQL listing teams with recent new-SDK $mcp_tool_call traffic.

    Raw ClickHouse rather than HogQL because HogQL execution is scoped to one team and
    this is the one cross-team question the pipeline asks. Only the deploy-configured
    database name is interpolated; the rest is parameterised by the caller.
    """
    return _DISCOVERY_SQL.format(database=database)


def measured_query_placeholders(date_from: datetime) -> dict[str, ast.Expr]:
    """The placeholder values the measured-server selects share."""
    return {
        "effective_tool": parse_expr(EFFECTIVE_TOOL_SQL),
        "effective_description": parse_expr(EFFECTIVE_DESCRIPTION_SQL),
        "date_from": ast.Constant(value=date_from),
        "source": ast.Constant(value=NEW_SDK_SOURCE),
    }


def measured_source() -> str:
    """The source marker new-SDK $mcp_tool_call events carry."""
    return NEW_SDK_SOURCE
