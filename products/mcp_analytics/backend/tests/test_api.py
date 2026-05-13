import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.models.event.util import create_event

from products.mcp_analytics.backend.facade import api, contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission


class TestMCPAnalyticsFacade(APIBaseTest):
    def test_create_feedback_submission(self) -> None:
        submission = api.create_feedback_submission(
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

        assert submission.kind == enums.SubmissionKind.FEEDBACK
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

    def test_list_missing_capability_submissions(self) -> None:
        api.create_missing_capability_submission(
            self.team,
            self.user,
            contracts.CreateMissingCapabilitySubmission(
                goal="debug a survey",
                missing_capability="Need a survey eligibility explainer",
                blocked=True,
            ),
        )

        submissions = api.list_missing_capability_submissions(self.team)

        assert len(submissions) == 1
        assert submissions[0].kind == enums.SubmissionKind.MISSING_CAPABILITY


class TestMCPAnalyticsMissingToolsFacade(ClickhouseTestMixin, APIBaseTest):
    def test_empty_when_no_clusters_and_no_embeddings(self) -> None:
        with patch(
            "posthog.hogql_queries.mcp_analytics.missing_tools_query_runner.MissingToolsCandidatesRunner._search_llm_stated_gaps",
            return_value=[],
        ):
            result = api.get_missing_tools_candidates(self.team)
        assert result.clustering_run_id == ""
        assert result.intent_clusters == []
        assert result.llm_stated_gaps == []

    def test_returns_clusters_from_latest_event(self) -> None:
        create_event(
            event_uuid=uuid.uuid4(),
            event="$mcp_intent_clusters",
            team=self.team,
            distinct_id=f"mcp_analytics_clustering_{self.team.id}",
            properties={
                "$mcp_clustering_run_id": "facade-run-1",
                "$mcp_window_start": "2026-05-01T00:00:00Z",
                "$mcp_window_end": "2026-05-08T00:00:00Z",
                "$mcp_total_intents_analyzed": 7,
                "$mcp_clusters": [
                    {
                        "cluster_id": 0,
                        "title": "Export dashboard as PDF",
                        "description": "Users repeatedly ask to export dashboards as PDF",
                        "gap_score": 0.9,
                        "size": 3,
                        "aggregate_error_rate": 0.6,
                        "aggregate_empty_rate": 0.1,
                        "avg_distinct_tools_attempted": 4.0,
                        "members": [
                            {
                                "intent": "export dashboard as PDF",
                                "stat": {
                                    "intent": "export dashboard as PDF",
                                    "total_calls": 6,
                                    "error_count": 4,
                                    "empty_response_count": 1,
                                    "distinct_tools_attempted": 5,
                                    "dominant_tool": "dashboard_get",
                                    "sample_session_ids": [],
                                },
                                "distance_to_centroid": 0.0,
                            }
                        ],
                    }
                ],
            },
            timestamp=datetime.now(UTC),
        )

        with patch(
            "posthog.hogql_queries.mcp_analytics.missing_tools_query_runner.MissingToolsCandidatesRunner._search_llm_stated_gaps",
            return_value=[],
        ):
            result = api.get_missing_tools_candidates(self.team)

        assert result.clustering_run_id == "facade-run-1"
        assert len(result.intent_clusters) == 1
        cluster = result.intent_clusters[0]
        assert cluster.title == "Export dashboard as PDF"
        assert cluster.gap_score == 0.9
        assert cluster.sample_intents[0].intent == "export dashboard as PDF"
