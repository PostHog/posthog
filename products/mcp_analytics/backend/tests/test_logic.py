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
                category=enums.FeedbackCategory.RESULTS,
            ),
        )

        assert submission.kind == MCPAnalyticsSubmission.Kind.FEEDBACK
        assert submission.summary == "Need clearer explanations for query failures"
        assert submission.category == MCPAnalyticsSubmission.FeedbackCategory.RESULTS

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
