from posthog.test.base import APIBaseTest

from products.mcp_analytics.backend.facade import api, contracts, enums


class TestMCPAnalyticsFacade(APIBaseTest):
    def test_create_feedback_submission(self) -> None:
        submission = api.create_feedback_submission(
            self.team,
            self.user,
            contracts.CreateFeedbackSubmission(
                goal="understand MCP usage",
                feedback="Need clearer explanations for query failures",
                category=enums.FeedbackCategory.RESULTS,
            ),
        )

        assert submission.kind == enums.SubmissionKind.FEEDBACK
        assert submission.category == enums.FeedbackCategory.RESULTS

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
