from parameterized import parameterized

from products.engineering_analytics.backend.logic.job_logs.coordinator import _github_source_params


class TestGithubSourceParams:
    def test_extracts_integration_and_repo(self):
        job_inputs = {"auth_method": {"github_integration_id": "42"}, "repository": "PostHog/posthog"}
        assert _github_source_params(job_inputs) == (42, "PostHog/posthog")

    @parameterized.expand(
        [
            ("auth_method_not_dict", {"auth_method": "oauth", "repository": "PostHog/posthog"}),
            ("missing_integration_id", {"auth_method": {}, "repository": "PostHog/posthog"}),
            ("missing_repo", {"auth_method": {"github_integration_id": "42"}}),
            (
                "unsafe_repo",
                {"auth_method": {"github_integration_id": "42"}, "repository": "PostHog/posthog/contents/x?ref=y"},
            ),
            ("none_job_inputs", None),
        ]
    )
    def test_returns_none_for_unusable_source(self, _name, job_inputs):
        assert _github_source_params(job_inputs) is None
