from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.apps import apps
from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from pydantic import ValidationError
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.models import Integration, OrganizationMembership, Team, User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportPullRequest,
    SignalReportSuggestedReviewer,
    SignalTeamConfig,
)
from products.signals.backend.monitor_pr import (
    PR_RESEARCH_DAILY_ATTEMPT_LIMIT,
    MonitorPRInput,
    PRMonitoringOutput,
    fail_monitoring_research,
    finish_monitoring_research,
    load_pull_request,
    monitor_key,
)
from products.signals.backend.monitor_pr_research import _context, research_pull_request
from products.signals.backend.presentation.monitor_pr import MonitorPRRequestSerializer
from products.signals.backend.pull_requests import update_pull_request_state
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.tasks import refresh_linked_pull_request_state, refresh_signals_github_repository_cache
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query

PR_URL = "https://github.com/example/widget/pull/42"


def _valid_output_payload() -> dict:
    return {
        "inspected_commit": "a" * 40,
        "metric": {
            "metric_id": "checkout",
            "title": "Completed checkouts",
            "kind": "occurrences",
            "role": "primary",
            "value_format": "count",
            "query": trends_metric_query(series=[{"kind": "EventsNode", "event": "checkout_completed"}]),
        },
        "check": {
            "title": "Checkout completions",
            "kind": "metric_threshold",
            "soak_hours": 24,
            "config": {
                "metric_id": "checkout",
                "comparison": {"operator": "gte", "value": 100},
                "monitoring": {"reference_period_minutes": 1440, "threshold_scaling": "linear"},
            },
        },
    }


class TestPRMonitoringOutputValidation(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "linear_non_additive_query",
                lambda payload: payload["metric"].update(
                    query=trends_metric_query(
                        series=[{"kind": "EventsNode", "event": "checkout_completed", "math": "dau"}]
                    )
                ),
            ),
            (
                "duplicate_query_on_check",
                lambda payload: payload["check"]["config"].update(query=payload["metric"]["query"]),
            ),
            (
                "baseline_without_period",
                lambda payload: payload["check"]["config"].update(baseline_value=90),
            ),
        ]
    )
    def test_rejects_invalid_monitoring_check_definitions(self, _name, mutate):
        payload = _valid_output_payload()
        mutate(payload)
        with self.assertRaises(ValidationError):
            PRMonitoringOutput.model_validate(payload)

    def test_request_serializer_bounds_optional_note(self):
        default_serializer = MonitorPRRequestSerializer(data={"pr_url": PR_URL})
        assert default_serializer.is_valid(), default_serializer.errors
        assert default_serializer.validated_data["note"] == ""

        oversized_serializer = MonitorPRRequestSerializer(data={"pr_url": PR_URL, "note": "x" * 4001})
        assert not oversized_serializer.is_valid()
        assert oversized_serializer.errors["note"][0].code == "max_length"


class TestMonitorPR(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        Integration.objects.create(
            team=self.team, kind="github", integration_id="123", config={"organization": "example"}
        )
        self.url = f"/api/projects/{self.team.id}/signals/monitor_pr/"
        self.pr = {
            "success": True,
            "title": "Improve checkout",
            "head_sha": "a" * 40,
            "head_repository": "example/widget",
            "base_branch": "main",
            "state": "open",
            "draft": False,
            "merged": False,
            "author": "another-author",
        }
        self.dispatched: list[tuple[str, MonitorPRInput]] = []

        async def start(_run, inputs, **kwargs):
            self.dispatched.append((kwargs["id"], inputs))

        client = AsyncMock()
        client.start_workflow.side_effect = start
        for mock in (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            patch.object(
                GitHubIntegration,
                "list_all_cached_repositories",
                autospec=True,
                return_value=[{"full_name": "example/widget"}],
            ),
            patch.object(GitHubIntegration, "installation_can_access_repository", return_value=True),
            patch.object(GitHubIntegration, "get_pull_request", side_effect=lambda *args: self.pr),
            patch.object(
                GitHubIntegration,
                "get_pull_request_diff",
                return_value={
                    "success": True,
                    "diff": "diff --git a/checkout.py b/checkout.py\n+track()\n",
                    "truncated": False,
                },
            ),
            patch("products.signals.backend.temporal.monitor_pr.async_connect", return_value=client),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def request_report(self, expected_status=202, url=None, note=None):
        payload = {"pr_url": PR_URL, **({"note": note} if note is not None else {})}
        response = self.client.post(url or self.url, payload)
        assert response.status_code == expected_status, response.json()
        report = SignalReport.objects.get(id=response.json()["report_id"])
        return report, self.dispatched[-1][1]

    def output(self):
        return PRMonitoringOutput.model_validate(_valid_output_payload())

    @parameterized.expand([(False,), (True,)])
    def test_request_assigns_initiator_and_replays_idempotently(self, dispatch_fails):
        if dispatch_fails:
            with patch("products.signals.backend.temporal.monitor_pr.async_connect", side_effect=ConnectionError):
                failed_res = self.client.post(self.url, {"pr_url": PR_URL})
                assert failed_res.status_code == 503
            assert SignalReport.objects.get(id=failed_res.json()["report_id"]).status == SignalReport.Status.FAILED
        report, inputs = self.request_report(expected_status=202)
        first_workflow_id = self.dispatched[-1][0]
        assert report.created_by_id == self.user.id
        claim = get_active_claim(team_id=self.team.id, report_id=str(report.id))
        assert claim is not None and claim.actor_user_id == self.user.id
        assert (
            SignalReportSuggestedReviewer.objects.for_team(self.team.id)
            .filter(report_id=report.id, user_uuid=self.user.uuid)
            .exists()
        )
        assert (
            self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/").json()["repo_slug"]
            == "example/widget"
        )
        response = self.client.post(self.url, {"pr_url": PR_URL})
        assert response.status_code == 200 and response.json()["idempotent_replay"] is True
        assert response.json()["report_id"] == str(report.id)
        assert SignalReport.objects.filter(team=self.team).count() == 1
        assert self.dispatched[-1] == (first_workflow_id, inputs)
        with patch("products.signals.backend.temporal.monitor_pr.async_connect", side_effect=ConnectionError):
            assert self.client.post(self.url, {"pr_url": PR_URL}).status_code == 503
        report.refresh_from_db()
        assert report.status == SignalReport.Status.IN_PROGRESS

    @parameterized.expand(
        [("merged",), ("merged_during_research",), ("open",), ("draft",), ("closed",), ("unmeasurable",)]
    )
    def test_research_and_merge_follow_monitoring_lifecycle(self, scenario):
        merged_at = timezone.now() - timedelta(hours=2)
        if scenario == "merged":
            self.pr.update(state="closed", merged=True, merged_at=merged_at.isoformat())
        elif scenario == "draft":
            self.pr.update(state="open", draft=True)
        pushes: list[tuple] = []
        with patch(
            "products.signals.backend.tasks.send_pull_request_ready_push.delay",
            side_effect=lambda *a, **kw: pushes.append((a, kw)),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                report, inputs = self.request_report()
            if scenario == "draft":
                stored_pr = SignalReportPullRequest.objects.for_team(self.team.id).get(
                    repository="example/widget", number=42
                )
                assert stored_pr.state == SignalReportPullRequest.State.DRAFT and pushes == []
            elif scenario in {"open", "merged_during_research"}:
                assert len(pushes) == 1
        if scenario == "merged_during_research":
            self.pr.update(state="closed", merged=True, merged_at=merged_at.isoformat())
        pr = load_pull_request(self.team.id, PR_URL)
        output = (
            PRMonitoringOutput(inspected_commit="a" * 40, unavailable=True)
            if scenario == "unmeasurable"
            else self.output()
        )
        refreshes: list[tuple] = []
        with patch(
            "products.signals.backend.tasks.refresh_linked_pull_request_state.delay",
            side_effect=lambda *a: refreshes.append(a),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                finish_monitoring_research(inputs, output, pr)
        report.refresh_from_db()
        if scenario == "unmeasurable":
            assert report.status == SignalReport.Status.PENDING_INPUT
            assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=report).exists()
            self.pr.update(state="closed", merged=True, merged_at=merged_at.isoformat())
            update_pull_request_state(
                team_id=self.team.id, repository="example/widget", number=42, state="merged", merged_at=merged_at
            )
            report.refresh_from_db()
            assert report.status == SignalReport.Status.PENDING_INPUT
            return
        if scenario not in {"merged", "merged_during_research"}:
            assert refreshes == [(self.team.id, PR_URL)]
            assert report.status == SignalReport.Status.READY
            check = SignalReportCheck.objects.for_team(self.team.id).get(report=report)
            assert check.status == SignalReportCheck.Status.PENDING
            if scenario == "draft":
                with self.captureOnCommitCallbacks(execute=True):
                    refresh_linked_pull_request_state(self.team.id, PR_URL)
                report.refresh_from_db()
                assert report.status == SignalReport.Status.READY
            self.pr.update(
                state="closed",
                draft=False,
                merged=scenario in {"open", "draft"},
                merged_at=merged_at.isoformat() if scenario in {"open", "draft"} else None,
            )
            with self.captureOnCommitCallbacks(execute=True):
                refresh_linked_pull_request_state(self.team.id, PR_URL)
            report.refresh_from_db()
        if scenario == "closed":
            assert report.status == SignalReport.Status.SUPPRESSED
        else:
            assert report.status == SignalReport.Status.MONITORING
            assert report.monitoring_started_at == merged_at
            assert report.metrics[0]["metric_id"] == "primary_metric"
            assert report.metrics[0]["role"] == "primary"
        claim = get_active_claim(team_id=self.team.id, report_id=str(report.id))
        if scenario == "closed":
            assert claim is None
        else:
            assert claim is not None and claim.actor_user_id == self.user.id
        assert (
            SignalReportSuggestedReviewer.objects.for_team(self.team.id)
            .filter(report_id=report.id, user_uuid=self.user.uuid)
            .exists()
        )

    @parameterized.expand(
        [
            ("unregistered_repo", "https://github.com/unregistered/widget/pull/42", None),
            ("issue_url", "https://github.com/example/widget/issues/42", None),
            ("files_url", "https://github.com/example/widget/pull/42/files", None),
            ("other_project", PR_URL, "other_project"),
            ("fork_pr", PR_URL, "fork"),
            ("expired_merge_window", PR_URL, "expired_merge"),
        ]
    )
    def test_only_trusted_registered_pull_requests_are_accepted(self, _name, url, mode):
        if mode == "other_project":
            other = Team.objects.create(organization=self.organization)
            Integration.objects.filter(team=self.team, kind="github").update(team=other)
        elif mode == "fork":
            self.pr["head_repository"] = "external-fork/widget"
        elif mode == "expired_merge":
            self.pr.update(
                state="closed",
                merged=True,
                merged_at=(timezone.now() - timedelta(days=91)).isoformat(),
            )
        response = self.client.post(self.url, {"pr_url": url})
        assert response.status_code == 400
        assert not SignalReport.objects.filter(team=self.team).exists()

    def test_failed_and_deleted_reports_can_be_restarted_and_child_env_resolves_canonically(self):
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        merged_at = timezone.now() - timedelta(hours=1)
        self.pr.update(state="closed", merged=True, merged_at=merged_at.isoformat())
        child_url = f"/api/projects/{child.id}/signals/monitor_pr/"

        report, inputs = self.request_report(url=child_url)
        first_workflow_id = self.dispatched[-1][0]
        assert report.team_id == self.team.id
        assert inputs.team_id == self.team.id

        fail_monitoring_research(inputs)
        report.refresh_from_db()
        assert report.status == SignalReport.Status.FAILED

        restarted, retried_inputs = self.request_report(expected_status=202, url=child_url)
        assert self.dispatched[-1][0] != first_workflow_id
        assert restarted.id == report.id and restarted.status == SignalReport.Status.IN_PROGRESS

        pr = load_pull_request(self.team.id, PR_URL)
        assert _context(inputs) is None
        fail_monitoring_research(inputs)
        finish_monitoring_research(inputs, self.output(), pr)
        restarted.refresh_from_db()
        assert restarted.status == SignalReport.Status.IN_PROGRESS

        finish_monitoring_research(retried_inputs, self.output(), pr)
        restarted.refresh_from_db()
        assert restarted.status == SignalReport.Status.MONITORING
        assert restarted.monitoring_started_at == merged_at

        restarted.save(update_fields=restarted.transition_to(SignalReport.Status.DELETED))
        fresh, _ = self.request_report(expected_status=202, url=child_url)
        assert fresh.id != restarted.id

    @parameterized.expand([("scopes",), ("ai_consent",), ("sandbox",)])
    def test_unauthorized_request_cannot_start_research(self, denied):
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="monitor",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["inbox:write"]
            if denied == "scopes"
            else ["inbox:write", "task:write", "query:read", "event_definition:read"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        if denied == "ai_consent":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(
            self.url,
            {"pr_url": PR_URL},
            HTTP_AUTHORIZATION=f"Bearer {raw}",
            HTTP_X_POSTHOG_SANDBOX_ORIGIN="1" if denied == "sandbox" else "",
        )
        assert response.status_code == 403, response.json()
        assert not self.dispatched
        assert not SignalReport.objects.filter(team=self.team).exists()

    def test_removed_member_cannot_start_queued_research(self):
        _, inputs = self.request_report()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).delete()
        with self.assertRaises(User.DoesNotExist):
            _context(inputs)

    @staticmethod
    def _search_item(number: int, repository: str = "example/widget") -> dict:
        created_at = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=number)).isoformat()
        return {
            "html_url": f"https://github.com/{repository}/pull/{number}",
            "title": f"Change {number}",
            "state": "open",
            "user": {"login": "example-author"},
            "created_at": created_at,
            "updated_at": created_at,
        }

    def test_pull_requests_list_filters_registered_repos_merges_installations_and_isolates_caller_reports(self):
        cache.clear()
        list_url = f"/api/projects/{self.team.id}/signals/pull_requests/"
        items = [self._search_item(999, "example/unregistered"), *(self._search_item(n) for n in range(60, 0, -1))]
        own = SignalReport.objects.create(
            team=self.team,
            created_by=self.user,
            scout_idempotency_key=monitor_key(self.user.id, "https://github.com/example/widget/pull/55"),
            status=SignalReport.Status.READY,
        )
        someone = User.objects.create_and_join(self.organization, email="someone@example.com", password="test")
        SignalReport.objects.create(
            team=self.team,
            created_by=someone,
            scout_idempotency_key=monitor_key(someone.id, "https://github.com/example/widget/pull/56"),
            status=SignalReport.Status.MONITORING,
        )

        def search(_gh_self, _method, _path, **kwargs):
            params = kwargs["params"]
            assert "author:example-author" in params["q"] and "user:example" in params["q"]
            assert params["sort"] == "created" and params["order"] == "desc"
            return Mock(ok=True, json=lambda: {"items": items})

        with (
            patch.object(User, "get_github_login", return_value="example-author"),
            patch.object(GitHubIntegration, "api_request", autospec=True, side_effect=search),
        ):
            response = self.client.get(list_url)
            assert response.status_code == 200, response.data
            results = response.data["results"]
            assert [pr["number"] for pr in results] == list(range(60, 10, -1))
            for pr in results:
                assert pr["report"] == ({"id": str(own.id), "status": "ready"} if pr["number"] == 55 else None)

            second = Integration.objects.create(
                team=self.team, kind="github", integration_id="456", config={"account": {"name": "second-org"}}
            )
            cache.clear()
            with (
                patch.object(
                    GitHubIntegration,
                    "list_all_cached_repositories",
                    lambda gh, **_: (
                        [{"full_name": "second-org/app"}]
                        if gh.integration.id == second.id
                        else [{"full_name": "example/widget"}]
                    ),
                ),
                patch.object(
                    GitHubIntegration,
                    "api_request",
                    lambda _gh, _m, _p, **kw: Mock(
                        ok=True,
                        json=lambda: {
                            "items": [
                                self._search_item(65, "second-org/app")
                                if "user:second-org" in kw["params"]["q"]
                                else self._search_item(60)
                            ]
                        },
                    ),
                ),
            ):
                merged = self.client.get(list_url)
                assert merged.status_code == 200
                assert [pr["url"] for pr in merged.data["results"]] == [
                    "https://github.com/second-org/app/pull/65",
                    "https://github.com/example/widget/pull/60",
                ]

    def test_pull_requests_list_gates_flag_and_sandbox_and_uses_personal_github_identity(self):
        list_url = f"/api/projects/{self.team.id}/signals/pull_requests/"
        with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=False):
            assert self.client.get(list_url).status_code == 403
        assert self.client.get(list_url, HTTP_X_POSTHOG_SANDBOX_ORIGIN="1").status_code == 403
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="999",
            created_by=self.user,
            config={"connecting_user_github_login": "team-fallback-login", "account": {"name": "other"}},
        )
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        response = self.client.get(f"/api/projects/{child.id}/signals/pull_requests/")
        assert response.status_code == 200
        assert response.data["github_login"] is None

    def test_research_creates_team_viewable_task_run_and_refreshes_stale_repo_cache(self):
        from asgiref.sync import async_to_sync, sync_to_async

        from products.tasks.backend.facade.agents import create_task_and_trigger

        cache.clear()
        queued_refreshes: list[tuple[int, int]] = []
        captured_start: dict = {}
        ended_runs: list[tuple[str, str | None]] = []
        created_runs: list = []

        async def fake_start(**kwargs):
            captured_start.update(kwargs)
            dto = await create_task_and_trigger(
                kwargs["prompt"],
                kwargs["context"],
                profile=kwargs["profile"],
                branch=kwargs.get("branch"),
                step_name=kwargs.get("step_name") or "",
                source=kwargs.get("source"),
                ai_stage=kwargs.get("ai_stage"),
                ai_agent_name=kwargs.get("ai_agent_name"),
                output_schema=kwargs.get("output_schema"),
                analytics_query_context=kwargs.get("analytics_query_context"),
            )
            await sync_to_async(kwargs["before_task_dispatch"], thread_sensitive=True)(dto.run_id)
            created_runs.append(dto)

            async def fake_end(status="completed", error=None):
                ended_runs.append((status, error))
                await sync_to_async(
                    apps.get_model("tasks", "TaskRun").objects.filter(id=dto.run_id).update,
                    thread_sensitive=True,
                )(status=status, error_message=error)
                await sync_to_async(
                    apps.get_model("tasks", "Task").objects.filter(id=dto.task_id).update,
                    thread_sensitive=True,
                )(status="idle")

            session = AsyncMock()
            session.end.side_effect = fake_end
            return session, fake_output

        with (
            patch(
                "products.signals.backend.tasks.refresh_signals_github_repository_cache.delay",
                side_effect=lambda team_id, integration_id: queued_refreshes.append((team_id, integration_id)),
            ),
            patch(
                "products.signals.backend.monitor_pr_research.database_sync_to_async_pool",
                side_effect=lambda fn: sync_to_async(fn, thread_sensitive=True),
            ),
            patch("products.signals.backend.monitor_pr_research.MultiTurnSession.start", side_effect=fake_start),
        ):
            embedded_query = trends_metric_query(
                series=[
                    {
                        "kind": "EventsNode",
                        "event": "checkout_completed",
                        "math": "avg",
                        "math_property": "duration_ms",
                        "name": "leaked_name",
                        "custom_name": "leaked_custom_name",
                        "response": {"leaked_series": "secret"},
                    }
                ]
            )
            embedded_query["source"]["response"] = {"results": [{"leaked": "secret"}]}
            duration_output = PRMonitoringOutput.model_validate(
                {
                    **_valid_output_payload(),
                    "metric": {
                        **_valid_output_payload()["metric"],
                        "kind": "duration",
                        "value_format": "duration",
                        "unit": "ms",
                        "query": embedded_query,
                    },
                    "check": {
                        **_valid_output_payload()["check"],
                        "config": {
                            "metric_id": "checkout",
                            "comparison": {"operator": "lte", "value": 500},
                            "monitoring": {"reference_period_minutes": 1440, "threshold_scaling": "fixed"},
                        },
                    },
                }
            )
            fake_output = duration_output
            report, inputs = self.request_report(note="  Focus on checkout latency  ")
            assert inputs.note == "Focus on checkout latency"
            load_pull_request(self.team.id, PR_URL)
            integration_id = Integration.objects.get(team=self.team, kind="github").id
            assert queued_refreshes == [(self.team.id, integration_id)]

            async_to_sync(research_pull_request)(inputs)
            assert captured_start.get("branch") is None
            assert "diff --git a/checkout.py" in captured_start["prompt"]
            assert '"note": "Focus on checkout latency"' in captured_start["prompt"]
            assert "git checkout" not in captured_start["prompt"]
            assert not SignalReportArtefact.objects.filter(
                report_id=report.id, type=SignalReportArtefact.ArtefactType.NOTE
            ).exists()
            assert len(created_runs) == 1
            dto = created_runs[0]
            assert SignalReportArtefact.objects.filter(
                report_id=report.id, type=SignalReportArtefact.ArtefactType.TASK_RUN
            ).exists()
            run_url = f"/api/projects/{self.team.id}/tasks/{dto.task_id}/runs/{dto.run_id}/"
            assert self.client.get(run_url).status_code == 200
            assert captured_start["context"].github_read_access is False
            assert captured_start["context"].github_token_scope == "read"
            assert "person:read" not in captured_start["context"].posthog_mcp_scopes
            assert "session_recording:read" not in captured_start["context"].posthog_mcp_scopes
            assert ended_runs == [("completed", None)]
            report.refresh_from_db()
            assert report.status == SignalReport.Status.READY
            assert report.metrics[0]["unit"] == "ms"
            assert "response" not in report.metrics[0]["query"]["source"]
            series_0 = report.metrics[0]["query"]["source"]["series"][0]
            assert not ({"response", "name", "custom_name"} & series_0.keys())
            check = SignalReportCheck.objects.for_team(self.team.id).get(report=report)
            assert check.title == "Post-merge check for example/widget#42"
            assert check.config["unit"] == "ms"
            assert "leaked" not in str(
                self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/").json()
            )
            narrow_raw = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="narrow-monitor",
                user=self.user,
                secure_value=hash_key_value(narrow_raw),
                scopes=["inbox:read", "inbox:write", "task:write", "query:read", "event_definition:read"],
                scoped_teams=[self.team.id],
            )
            api_client = APIClient()
            narrow_res = api_client.post(
                self.url,
                {"pr_url": "https://github.com/example/widget/pull/44"},
                HTTP_AUTHORIZATION=f"Bearer {narrow_raw}",
            )
            assert narrow_res.status_code == 202, narrow_res.json()
            narrow_inputs = self.dispatched[-1][1]
            narrow_ctx = _context(narrow_inputs)
            assert narrow_ctx is not None
            assert isinstance(narrow_ctx.posthog_mcp_scopes, list)
            assert "action:read" not in narrow_ctx.posthog_mcp_scopes
            action_output = PRMonitoringOutput.model_validate(
                {
                    **_valid_output_payload(),
                    "metric": {
                        **_valid_output_payload()["metric"],
                        "query": trends_metric_query(series=[{"kind": "ActionsNode", "id": 1}]),
                    },
                }
            )
            cohort_math_output = PRMonitoringOutput.model_validate(
                {
                    **_valid_output_payload(),
                    "metric": {
                        **_valid_output_payload()["metric"],
                        "kind": "custom",
                        "query": trends_metric_query(
                            series=[
                                {
                                    "kind": "EventsNode",
                                    "event": "checkout_completed",
                                    "math": "hogql",
                                    "math_hogql": "countIf(person_id IN COHORT 12)",
                                }
                            ]
                        ),
                    },
                    "check": {
                        **_valid_output_payload()["check"],
                        "config": {
                            "metric_id": "checkout",
                            "comparison": {"operator": "gte", "value": 10},
                            "monitoring": {"reference_period_minutes": 1440, "threshold_scaling": "fixed"},
                        },
                    },
                }
            )
            for forbidden in (action_output, cohort_math_output):
                with self.assertRaises(ValueError):
                    finish_monitoring_research(
                        narrow_inputs, forbidden, load_pull_request(self.team.id, narrow_inputs.pr_url)
                    )
            finish_monitoring_research(
                narrow_inputs, self.output(), load_pull_request(self.team.id, narrow_inputs.pr_url)
            )
            teammate = User.objects.create_and_join(self.organization, email="teammate@example.com", password="test")
            self.client.force_login(teammate)
            assert self.client.get(run_url).status_code == 200
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
                {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
            ]
            self.organization.save(update_fields=["available_product_features"])
            AccessControl.objects.create(team=self.team, resource="action", resource_id="777", access_level="none")
            denied_report, denied_inputs = self._request_for_pr("https://github.com/example/widget/pull/43")
            ended_runs.clear()
            fake_output = duration_output.model_copy(update={"inspected_commit": "b" * 40})
            with self.assertRaises(ValueError):
                async_to_sync(research_pull_request)(denied_inputs)
            assert len(ended_runs) == 1 and ended_runs[0][0] == "failed" and ended_runs[0][1]
            assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=denied_report).exists()

            ended_runs.clear()
            fake_output = PRMonitoringOutput.model_validate(
                {
                    **_valid_output_payload(),
                    "metric": {
                        **_valid_output_payload()["metric"],
                        "query": trends_metric_query(series=[{"kind": "ActionsNode", "id": 777}]),
                    },
                }
            )
            with self.assertRaises(ValueError):
                async_to_sync(research_pull_request)(denied_inputs)
            assert len(ended_runs) == 1 and ended_runs[0][0] == "failed" and ended_runs[0][1]
            assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=denied_report).exists()

            denied_task_acl = AccessControl.objects.create(
                team=self.team, resource="task", resource_id=None, access_level="none"
            )
            with self.assertRaises(ValueError):
                finish_monitoring_research(
                    denied_inputs, self.output(), load_pull_request(self.team.id, denied_inputs.pr_url)
                )
            denied_task_acl.delete()

            SignalReport.objects.filter(id=report.id).update(
                status=SignalReport.Status.IN_PROGRESS,
                run_count=1,
                self_driving_funding={"funding": "existing", "report_pass_key": "report-pass:summary"},
            )
            self.client.force_login(self.user)
            before_dispatches = len(self.dispatched)
            replay_summary = self.client.post(self.url, {"pr_url": PR_URL})
            assert replay_summary.status_code == 200 and replay_summary.json()["idempotent_replay"] is True
            assert len(self.dispatched) == before_dispatches

    def _request_for_pr(self, pr_url: str) -> tuple[SignalReport, MonitorPRInput]:
        response = self.client.post(self.url, {"pr_url": pr_url})
        assert response.status_code == 202, response.json()
        return SignalReport.objects.get(id=response.json()["report_id"]), self.dispatched[-1][1]

    def test_rate_limits_pending_repo_discovery_and_daily_attempt_caps(self):
        list_url = f"/api/projects/{self.team.id}/signals/pull_requests/"
        rate_error = GitHubRateLimitError("rate limited", retry_after=45)
        with (
            patch.object(User, "get_github_login", return_value="example-author"),
            patch.object(GitHubIntegration, "api_request", side_effect=rate_error),
            patch.object(GitHubIntegration, "get_pull_request", side_effect=rate_error),
        ):
            list_rate = self.client.get(list_url)
            post_rate = self.client.post(self.url, {"pr_url": PR_URL})
        assert list_rate.status_code == 429 and list_rate.headers.get("Retry-After") == "45"
        assert post_rate.status_code == 429 and post_rate.headers.get("Retry-After") == "45"

        integration = Integration.objects.get(team=self.team, kind="github")
        with (
            patch.object(User, "get_github_login", return_value="example-author"),
            patch.object(GitHubIntegration, "list_all_cached_repositories", return_value=[]),
        ):
            assert self.client.post(self.url, {"pr_url": PR_URL}).status_code == 503
            assert self.client.get(list_url).status_code == 503
            integration.repository_cache = []
            integration.repository_cache_updated_at = timezone.now()
            integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
            assert self.client.post(self.url, {"pr_url": PR_URL}).status_code == 400
            empty_list = self.client.get(list_url)
            assert empty_list.status_code == 200 and empty_list.data["results"] == []

        for _ in range(PR_RESEARCH_DAILY_ATTEMPT_LIMIT):
            report, inputs = self.request_report(expected_status=202)
            fail_monitoring_research(inputs)
        capped = self.client.post(self.url, {"pr_url": PR_URL})
        assert capped.status_code == 429 and int(capped.headers["Retry-After"]) >= 1

    def test_unmeasured_retries_parent_inbox_access_and_daily_project_cap(self):
        report, inputs = self.request_report()
        pr = load_pull_request(self.team.id, PR_URL)
        finish_monitoring_research(inputs, PRMonitoringOutput(inspected_commit="a" * 40, unavailable=True), pr)
        report.refresh_from_db()
        assert report.status == SignalReport.Status.PENDING_INPUT

        restarted, retry_inputs = self.request_report(expected_status=202)
        assert restarted.id == report.id
        SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.POTENTIAL)
        restored, restored_inputs = self.request_report(expected_status=202)
        assert restored.id == report.id and restored_inputs.attempt_key != retry_inputs.attempt_key
        finish_monitoring_research(restored_inputs, self.output(), pr)

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save(update_fields=["available_product_features"])
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child")
        member = User.objects.create_and_join(self.organization, email="child-only@example.com", password="test")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        parent_block = AccessControl.objects.create(
            team=self.team, resource="task", resource_id=None, access_level="none", organization_member=membership
        )
        AccessControl.objects.create(
            team=child, resource="task", resource_id=None, access_level="editor", organization_member=membership
        )
        member_client = APIClient()
        member_client.force_login(member)
        assert member_client.get(f"/api/projects/{child.id}/signals/pull_requests/").status_code == 403
        assert (
            member_client.post(f"/api/projects/{child.id}/signals/monitor_pr/", {"pr_url": PR_URL}).status_code == 403
        )
        parent_block.delete()

        SignalTeamConfig.objects.update_or_create(team=self.team, defaults={"max_reports_per_day": 1})
        assert self.client.post(self.url, {"pr_url": "https://github.com/example/widget/pull/99"}).status_code == 429

    def test_partial_browser_integration_failure_window_eligibility_and_paced_repo_sync(self):
        cache.clear()
        second = Integration.objects.create(
            team=self.team, kind="github", integration_id="456", config={"organization": "healthy-org"}
        )
        old_merged = self._search_item(10, "healthy-org/app")
        old_merged["state"] = "closed"
        old_merged["pull_request"] = {"merged_at": (timezone.now() - timedelta(days=95)).isoformat()}
        fresh_open = self._search_item(11, "healthy-org/app")

        def list_repos(gh, **kwargs):
            return (
                [{"full_name": "healthy-org/app"}]
                if gh.integration.id == second.id
                else [{"full_name": "example/widget"}]
            )

        def search_api(gh, *args, **kwargs):
            if gh.integration.id != second.id:
                raise GitHubIntegrationError("broken installation")
            return Mock(ok=True, json=lambda: {"items": [fresh_open, old_merged]})

        with (
            patch.object(User, "get_github_login", return_value="example-author"),
            patch.object(GitHubIntegration, "list_all_cached_repositories", list_repos),
            patch.object(GitHubIntegration, "api_request", search_api),
        ):
            res = self.client.get(f"/api/projects/{self.team.id}/signals/pull_requests/")
        assert res.status_code == 200
        assert res.data["results"][0]["monitoring_disabled_reason"] is None
        assert "90 days" in (res.data["results"][1]["monitoring_disabled_reason"] or "")

        seen_pages: list[int] = []

        def paged_repos(_gh, *, page=1, per_page=100, priority=None):
            seen_pages.append(page)
            if len(seen_pages) == 2:
                raise GitHubEgressBudgetExhausted("shed", scope="installation:456")
            if page == 1:
                return [{"id": 1, "name": "one", "full_name": "healthy-org/one"}], True
            return [{"id": 2, "name": "two", "full_name": "healthy-org/two"}], False

        with (
            patch.object(GitHubIntegration, "list_repositories", paged_repos),
            patch.object(GitHubIntegration, "_wait_for_budget", lambda _gh: None),
            patch("products.signals.backend.tasks.github_installation_pace_seconds", return_value=120),
        ):
            with self.assertRaises(Exception):
                refresh_signals_github_repository_cache(self.team.id, second.id)
            refresh_signals_github_repository_cache(self.team.id, second.id)
        second.refresh_from_db()
        assert seen_pages == [1, 2, 2]
        assert [repo["full_name"] for repo in second.repository_cache] == ["healthy-org/one", "healthy-org/two"]
