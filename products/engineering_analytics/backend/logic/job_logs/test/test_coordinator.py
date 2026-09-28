from types import SimpleNamespace

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.job_logs.activity import FetchDepotJobLogInputs
from products.engineering_analytics.backend.logic.job_logs.coordinator import (
    DepotAttemptCursor,
    DepotDiscovery,
    DepotDiscoveryInputs,
    _discover_failed_depot_attempts,
    _discover_jobs_with_diagnostics,
    _github_source_params,
    _query_jobs_with_diagnostics,
)
from products.engineering_analytics.backend.logic.sources import DEPOT_JOB_ATTEMPTS_SCHEMA
from products.engineering_analytics.backend.logic.views.source_schema import DEPOT_JOB_ATTEMPTS_COLUMNS
from products.engineering_analytics.backend.tests._github_fixtures import create_github_warehouse_table, link_schema
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


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


class TestDiscoverJobsWithDiagnostics:
    @override_settings(OTLP_LOGS_INGEST_ENDPOINT="")
    def test_discovers_nothing_when_logs_endpoint_unset(self):
        # The coordinator schedule is registered but must stay inert until the Logs endpoint is
        # deployed: discovery returns [] (without querying the warehouse) so no child workflows fan
        # out. Drops the guard and this fails by hitting the DB and returning rows.
        assert _discover_jobs_with_diagnostics("2026-06-29T00:00:00+00:00") == []
        assert _discover_failed_depot_attempts(
            DepotDiscoveryInputs(cutoff_iso="2026-06-29T00:00:00+00:00", cursors={})
        ) == DepotDiscovery(attempts=[], cursors={})


class TestDiscoverFailedDepotAttempts(ClickhouseTestMixin, BaseTest):
    @override_settings(OTLP_LOGS_INGEST_ENDPOINT="http://localhost:8010/i/v1/logs")
    def test_discovers_recent_failed_attempts_with_decoded_ids(self) -> None:
        # Only recent failed attempts are fetched, keyed by the integer ids the curated views and CI
        # traces carry. A push run's id has no integer form, so its logs could never join and it is
        # skipped rather than emitted under a wrong run_id.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src-depot",
            connection_id="src-depot",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.DEPOT,
            prefix="ci",
            job_inputs={"api_token": "depot-tok", "repository": "PostHog/posthog"},
        )

        def attempt(
            attempt_id: str, status: str, finished: str, *, run_id: str = "427q556wmn", run_workflow_count: int = 1
        ) -> dict:
            return dict.fromkeys(DEPOT_JOB_ATTEMPTS_COLUMNS) | {
                "run_id": run_id,
                "run_workflow_count": run_workflow_count,
                "workflow_id": "cccccccccc",
                "repo": "PostHog/posthog",
                "head_sha": "abc1234",
                "workflow_name": "Backend CI on Depot",
                "job_key": "ci-backend.yml:turbo-tests:matrix-38",
                "attempt_id": attempt_id,
                "attempt": 1,
                "attempt_status": status,
                "attempt_finished_at": finished,
            }

        table_name = create_github_warehouse_table(
            self,
            "depot_job_attempts",
            DEPOT_JOB_ATTEMPTS_COLUMNS,
            [
                attempt("zf6sbbn2wh", "failed", "2026-09-24T14:55:00.000Z"),
                attempt("3v4pbsqvfc", "finished", "2026-09-24T14:59:00.000Z"),
                attempt("b82nsv77wl", "failed", "2026-09-22T14:52:30.000Z"),
                attempt("q28m5dl5rg", "failed", "2026-09-24T14:53:00.000Z", run_id="ps_59s92fgx6c"),
                # A run with two workflows takes the workflow's id, as the runs view keys it.
                attempt("h8qn5x801q", "failed", "2026-09-24T14:54:00.000Z", run_id="bbbbbbbbbb", run_workflow_count=2),
            ],
            source=source,
            prefix="ci",
        )
        link_schema(
            self.team,
            source,
            name=DEPOT_JOB_ATTEMPTS_SCHEMA,
            table=DataWarehouseTable.objects.get(team=self.team, name=table_name),
        )

        def fetch_inputs(attempt_id: str, run_id: int, job_id: int) -> FetchDepotJobLogInputs:
            return FetchDepotJobLogInputs(
                team_id=self.team.pk,
                source_id=str(source.id),
                attempt_id=attempt_id,
                run_id=run_id,
                job_id=job_id,
                repo="PostHog/posthog",
                workflow_name="Backend CI on Depot",
                job_name="ci-backend.yml:turbo-tests:matrix-38",
                run_attempt=1,
                head_sha="abc1234",
            )

        two_workflow_run = fetch_inputs("h8qn5x801q", run_id=223978965517241, job_id=300989664396052)
        one_workflow_run = fetch_inputs("zf6sbbn2wh", run_id=80213453736890, job_id=579485267642625)
        window_start = DepotDiscoveryInputs(cutoff_iso="2026-09-24T00:00:00+00:00", cursors={})
        assert _discover_failed_depot_attempts(window_start) == DepotDiscovery(
            attempts=[two_workflow_run, one_workflow_run], cursors={}
        )

        # A backlog over the cap pages forward across ticks. Without the cursor every tick reads the
        # same first page, and the attempts after it leave the lookback window without a fetch.
        with patch("products.engineering_analytics.backend.logic.job_logs.coordinator.MAX_DISCOVERED_JOBS", 2):
            first_tick = _discover_failed_depot_attempts(window_start)
            second_tick = _discover_failed_depot_attempts(
                DepotDiscoveryInputs(cutoff_iso=window_start.cutoff_iso, cursors=first_tick.cursors)
            )
        cursor = DepotAttemptCursor(finished_at="2026-09-24T14:54:00.000Z", attempt_id="h8qn5x801q")
        assert first_tick == DepotDiscovery(attempts=[two_workflow_run], cursors={str(source.id): cursor})
        assert second_tick == DepotDiscovery(attempts=[one_workflow_run], cursors={})


class TestQueryJobsWithDiagnostics:
    @patch("products.engineering_analytics.backend.logic.job_logs.coordinator.execute_hogql_query")
    def test_bypasses_warehouse_access_control(self, mock_execute):
        # The sweep runs with no request user, so without bypass HogQL marks the team's own
        # workflow_jobs warehouse table denied and the query raises "You don't have access to table" —
        # the worker then silently emits nothing. Locks in the bypass that makes the trusted query work.
        mock_execute.return_value = SimpleNamespace(columns=["job_id"], results=[])
        _query_jobs_with_diagnostics(Team(pk=1), "devex_", "2026-06-30T00:00:00+00:00", "PostHog/posthog")
        mock_execute.assert_called_once()
        assert mock_execute.call_args.kwargs["bypass_warehouse_access_control"] is True
