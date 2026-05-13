from posthog.hogql_queries.mcp_analytics.missing_tools_query_runner import (
    MissingToolsCandidatesRunner,
)
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


def get_missing_tools_candidates(team: Team) -> contracts.MissingToolsCandidates:
    """Return ranked candidate missing MCP tools for this team.

    Combines pre-computed intent clusters (from $mcp_intent_clusters events written
    by the daily Temporal workflow) with on-demand semantic search over $ai_span
    reasoning text for LLM-stated tool gaps.
    """
    result = MissingToolsCandidatesRunner(team=team).run()
    return contracts.MissingToolsCandidates(
        clustering_run_id=result.clustering_run_id,
        window_start=result.window_start,
        window_end=result.window_end,
        intent_clusters=[
            contracts.IntentCluster(
                cluster_id=c.cluster_id,
                title=c.title,
                description=c.description,
                gap_score=c.gap_score,
                size=c.size,
                aggregate_error_rate=c.aggregate_error_rate,
                aggregate_empty_rate=c.aggregate_empty_rate,
                avg_distinct_tools_attempted=c.avg_distinct_tools_attempted,
                sample_intents=[
                    contracts.IntentClusterSampleIntent(
                        intent=s.intent,
                        total_calls=s.total_calls,
                        error_rate=s.error_rate,
                        empty_rate=s.empty_rate,
                    )
                    for s in c.sample_intents
                ],
            )
            for c in result.intent_clusters
        ],
        llm_stated_gaps=[
            contracts.LLMStatedGap(
                probe_phrase=g.probe_phrase,
                matched_text=g.matched_text,
                distance=g.distance,
                document_id=g.document_id,
                timestamp=g.timestamp,
            )
            for g in result.llm_stated_gaps
        ],
    )
