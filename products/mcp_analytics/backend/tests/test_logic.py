from posthog.test.base import APIBaseTest

from products.mcp_analytics.backend import logic
from products.mcp_analytics.backend.facade import contracts, enums
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission


class TestMCPAnalyticsLogic(APIBaseTest):
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
