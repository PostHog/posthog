from posthog.test.base import APIBaseTest

from products.mcp_analytics.backend.models import MCPAnalyticsSubmission


class TestMCPAnalyticsSubmissionModel(APIBaseTest):
    def test_defaults_blank_fields(self) -> None:
        submission = MCPAnalyticsSubmission.objects.create(
            team=self.team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
            goal="understand MCP usage",
            summary="Feedback entry",
        )

        assert submission.category == ""
        assert submission.blocked is None
        assert submission.attempted_tool == ""
        assert submission.mcp_session_id == ""
