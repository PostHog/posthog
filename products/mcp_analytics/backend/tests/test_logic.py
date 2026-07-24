from posthog.test.base import APIBaseTest

from django.utils import timezone

from products.mcp_analytics.backend import logic
from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPIntentClusterSnapshot
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPAnalyticsLogic(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def test_create_feedback_submission(self) -> None:
        submission = logic.create_feedback_submission(
            self.team,
            self.user,
            contracts.CreateFeedbackSubmission(
                goal="understand MCP usage",
                feedback="Need clearer explanations for query failures",
                category=MCPAnalyticsSubmission.FeedbackCategory.RESULTS,
                context=contracts.SubmissionContext(
                    attempted_tool="query_run",
                    mcp_client_name="Claude Desktop",
                    mcp_client_version="1.0.0",
                    mcp_protocol_version="2025-03-26",
                    mcp_transport="streamable_http",
                    mcp_session_id="session-123",
                    mcp_trace_id="trace-456",
                ),
            ),
        )

        assert submission.kind == MCPAnalyticsSubmission.Kind.FEEDBACK
        assert submission.goal == "understand MCP usage"
        assert submission.summary == "Need clearer explanations for query failures"
        assert submission.category == MCPAnalyticsSubmission.FeedbackCategory.RESULTS
        assert submission.attempted_tool == "query_run"
        assert submission.mcp_client_name == "Claude Desktop"
        assert submission.mcp_client_version == "1.0.0"
        assert submission.mcp_protocol_version == "2025-03-26"
        assert submission.mcp_transport == "streamable_http"
        assert submission.mcp_session_id == "session-123"
        assert submission.mcp_trace_id == "trace-456"

    def test_list_submissions_filters_by_kind(self) -> None:
        logic.create_feedback_submission(
            self.team,
            self.user,
            contracts.CreateFeedbackSubmission(
                goal="understand MCP usage",
                feedback="Feedback entry",
            ),
        )
        logic.create_missing_capability_submission(
            self.team,
            self.user,
            contracts.CreateMissingCapabilitySubmission(
                goal="debug a survey",
                missing_capability="Need a survey eligibility explainer",
            ),
        )

        submissions = logic.list_submissions(self.team, enums.SubmissionKind.FEEDBACK)

        assert [submission.kind for submission in submissions] == [MCPAnalyticsSubmission.Kind.FEEDBACK]


class TestGetIntentClusterSnapshot(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def test_returns_empty_idle_snapshot_when_no_row_exists(self) -> None:
        snapshot = logic.get_intent_cluster_snapshot(self.team)

        assert snapshot.status == MCPIntentClusterSnapshot.Status.IDLE
        assert snapshot.clusters == []
        assert snapshot.last_computed_at is None
        assert snapshot.last_computed_by_email == ""
        assert snapshot.computed_with is None

    def test_maps_stored_snapshot_to_dto(self) -> None:
        now = timezone.now()
        MCPIntentClusterSnapshot.objects.create(
            team=self.team,
            status=MCPIntentClusterSnapshot.Status.IDLE,
            last_computed_at=now,
            last_computed_by=self.user,
            clusters={
                "clusters": [
                    {
                        "id": 0,
                        "label": "check feature flag rollout",
                        "intent_count": 2,
                        "call_count": 14,
                        "error_count": 1,
                        "error_rate_pct": 7.1,
                        "routing_entropy": 0.1,
                        "tool_distribution": [
                            {"tool": "feature_flag_get", "count": 12, "pct": 85.7, "errors": 1, "error_rate_pct": 8.3},
                            {"tool": "query_run", "count": 2, "pct": 14.3, "errors": 0, "error_rate_pct": 0.0},
                        ],
                        "sample_intents": ["check feature flag rollout", "look up feature flag status"],
                    }
                ],
                "computed_with": {
                    "distance_threshold": 0.2,
                    "embedding_model": "text-embedding-3-small-1536",
                    "n_intents": 2,
                    "n_clusters": 1,
                },
            },
        )

        snapshot = logic.get_intent_cluster_snapshot(self.team)

        assert snapshot.status == MCPIntentClusterSnapshot.Status.IDLE
        assert snapshot.last_computed_by_email == self.user.email
        assert len(snapshot.clusters) == 1
        cluster = snapshot.clusters[0]
        assert cluster.label == "check feature flag rollout"
        assert cluster.intent_count == 2
        assert cluster.call_count == 14
        assert len(cluster.tool_distribution) == 2
        assert cluster.tool_distribution[0].tool == "feature_flag_get"
        assert cluster.tool_distribution[0].error_rate_pct == 8.3
        assert snapshot.computed_with is not None
        assert snapshot.computed_with.n_clusters == 1

    def test_stale_computing_snapshot_is_auto_flipped_to_error(self) -> None:
        from datetime import timedelta

        from products.mcp_analytics.backend.logic import STALE_COMPUTING_THRESHOLD

        row = MCPIntentClusterSnapshot.objects.create(
            team=self.team,
            status=MCPIntentClusterSnapshot.Status.COMPUTING,
        )
        # Backdate updated_at past the threshold so the read should auto-recover.
        stale = timezone.now() - STALE_COMPUTING_THRESHOLD - timedelta(seconds=30)
        MCPIntentClusterSnapshot.objects.filter(pk=row.pk).update(updated_at=stale)

        snapshot = logic.get_intent_cluster_snapshot(self.team)

        assert snapshot.status == MCPIntentClusterSnapshot.Status.ERROR
        assert "did not complete" in snapshot.error_message

        row.refresh_from_db()
        assert row.status == MCPIntentClusterSnapshot.Status.ERROR

    def test_fresh_computing_snapshot_is_left_alone(self) -> None:
        MCPIntentClusterSnapshot.objects.create(
            team=self.team,
            status=MCPIntentClusterSnapshot.Status.COMPUTING,
        )

        snapshot = logic.get_intent_cluster_snapshot(self.team)

        # Recently updated COMPUTING rows pass through unmodified.
        assert snapshot.status == MCPIntentClusterSnapshot.Status.COMPUTING
        assert snapshot.error_message == ""
