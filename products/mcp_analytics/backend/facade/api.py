from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_analytics.backend import logic
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

from . import contracts
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


def list_mcp_sessions(
    team: Team, limit: int, offset: int, search: str = "", order_by: str = ""
) -> contracts.MCPSessionsPage:
    return logic.list_mcp_sessions(team, limit=limit, offset=offset, search=search, order_by=order_by)


def list_mcp_tool_calls(team: Team, session_id: str) -> list[contracts.MCPToolCall]:
    return logic.list_mcp_tool_calls(team, session_id=session_id)


def generate_session_intent(team: Team, session_id: str) -> str:
    """Generate (or return the cached) intent summary for an MCP session.

    Shared entry point for the UI's on-demand button and any future caller
    (e.g. clustering). Persists the result to ``MCPSession.intent``.
    """
    return logic.generate_session_intent(team, session_id=session_id)


def get_intent_cluster_snapshot(team: Team) -> contracts.IntentClusterSnapshot:
    return logic.get_intent_cluster_snapshot(team)


def trigger_intent_cluster_recompute(team: Team, user: User | None) -> None:
    """Kick off the intent cluster recompute Temporal workflow.

    Returns immediately. Use ``get_intent_cluster_snapshot`` to poll status —
    the workflow's compute activity writes the snapshot status (COMPUTING →
    IDLE/ERROR) as it runs.
    """
    import time
    import uuid
    import asyncio

    from django.conf import settings

    from posthog.temporal.common.client import async_connect
    from posthog.temporal.mcp_analytics.intent_clustering.constants import CHILD_WORKFLOW_ID_PREFIX, WORKFLOW_NAME
    from posthog.temporal.mcp_analytics.intent_clustering.models import IntentClusteringWorkflowInputs

    from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot

    # Flip to COMPUTING before dispatching so the 202 response and any
    # immediate poll see consistent state. The workflow's activity
    # re-asserts COMPUTING on pickup; both writes are idempotent.
    MCPIntentClusterSnapshot.objects.update_or_create(
        team=team,
        defaults={
            "status": MCPIntentClusterSnapshot.Status.COMPUTING,
            "error_message": "",
            "last_computed_by": user,
        },
    )

    workflow_id = f"{CHILD_WORKFLOW_ID_PREFIX}-{team.id}-adhoc-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

    # Create + use the Temporal client inside one event loop. sync_connect()
    # would build the client in asgiref's managed loop and then asyncio.run()
    # would call start_workflow in a different loop; the temporalio Rust
    # bridge is currently loop-agnostic but the inconsistency is fragile.
    # Matches the cluster_mcp_intents management command pattern.
    async def _start() -> None:
        client = await async_connect()
        await client.start_workflow(
            WORKFLOW_NAME,
            IntentClusteringWorkflowInputs(team_id=team.id, user_id=user.id if user else None),
            id=workflow_id,
            task_queue=settings.MCPA_TASK_QUEUE,
        )

    asyncio.run(_start())
