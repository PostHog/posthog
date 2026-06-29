from django.test import override_settings

from parameterized import parameterized

from products.engineering_analytics.backend.logic.job_logs.coordinator import (
    _discover_failed_jobs,
    _github_source_params,
)


class TestGithubSourceParams:
    def test_extracts_integration_and_repo(self):
        job_inputs = {"auth_method": {"github_integration_id": "42"}, "repository": "PostHog/posthog"}
        assert _github_source_params(job_inputs) == (42, "PostHog/posthog")

    def test_extracts_from_flat_auth_shape(self):
        job_inputs = {"auth_method": "oauth", "github_integration_id": "42", "repository": "PostHog/posthog"}
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
            ("string_job_inputs", "not a dict"),
            ("list_job_inputs", ["not", "a", "dict"]),
        ]
    )
    def test_returns_none_for_unusable_source(self, _name, job_inputs):
        assert _github_source_params(job_inputs) is None


class TestDiscoverFailedJobs:
    @override_settings(OTLP_LOGS_INGEST_ENDPOINT="")
    def test_discovers_nothing_when_logs_endpoint_unset(self):
        # The coordinator schedule is registered but must stay inert until the Logs endpoint is
        # deployed: discovery returns [] (without querying the warehouse) so no child workflows fan
        # out. Drops the guard and this fails by hitting the DB and returning rows.
        assert _discover_failed_jobs("2026-06-29T00:00:00+00:00") == []
