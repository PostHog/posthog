from types import SimpleNamespace

from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.job_logs.coordinator import (
    _discover_failed_jobs,
    _github_source_params,
    _query_failed_jobs,
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


class TestQueryFailedJobs:
    @patch("products.engineering_analytics.backend.logic.job_logs.coordinator.execute_hogql_query")
    def test_bypasses_warehouse_access_control(self, mock_execute):
        # The sweep runs with no request user, so without bypass HogQL marks the team's own
        # workflow_jobs warehouse table denied and the query raises "You don't have access to table" —
        # the worker then silently emits nothing. Locks in the bypass that makes the trusted query work.
        mock_execute.return_value = SimpleNamespace(columns=["job_id"], results=[])
        _query_failed_jobs(Team(pk=1), "devex_", "2026-06-30T00:00:00+00:00")
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["bypass_warehouse_access_control"] is True
