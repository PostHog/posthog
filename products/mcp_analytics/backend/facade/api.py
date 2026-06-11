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
    """Kick off the intent cluster recompute Celery task.

    Returns immediately. Use ``get_intent_cluster_snapshot`` to poll status.
    """
    # Imports here to avoid loading Celery at module import time.
    from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot
    from products.mcp_analytics.backend.tasks.tasks import compute_intent_clusters

    # Flip to COMPUTING before enqueuing so the 202 response and any
    # immediate poll see consistent state. The task re-asserts COMPUTING
    # on pickup; both writes are idempotent.
    MCPIntentClusterSnapshot.objects.update_or_create(
        team=team,
        defaults={
            "status": MCPIntentClusterSnapshot.Status.COMPUTING,
            "error_message": "",
            "last_computed_by": user,
        },
    )
    compute_intent_clusters.delay(team.id, user.id if user else None)
