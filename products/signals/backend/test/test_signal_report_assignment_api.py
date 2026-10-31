import json
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, call, patch

from django.apps import apps
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.egress.limiter.policies import Priority
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.implementation_pr import ImplementationPr, primary_pull_request
from products.signals.backend.models import (
    SignalActorKind,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportPullRequest,
)
from products.signals.backend.report_assignments import update_assignments_for_pull_request
from products.signals.backend.report_claims import get_active_claim, get_active_claims, responsible_users
from products.signals.backend.report_monitoring_attempts import complete_implementation


class TestPrimaryPullRequest(SimpleTestCase):
    @parameterized.expand(
        [
            ("open", ["closed", "merged", "open"], "open"),
            ("draft", ["merged", "draft"], "draft"),
            ("unknown", ["closed", "unknown"], "unknown"),
            ("merged", ["closed", "merged"], "merged"),
        ]
    )
    def test_primary_prefers_unfinished_then_merged(self, _name: str, states: list[str], expected: str) -> None:
        prs = [
            ImplementationPr(url=f"https://github.com/example/app/pull/{i}", state=state, merged=state == "merged")
            for i, state in enumerate(states, 1)
        ]
        assert primary_pull_request(prs).state == expected
        assert primary_pull_request(list(reversed(prs))) == primary_pull_request(prs)


class TestSignalReportAssignmentAPI(APIBaseTest):
    def _create_check(self, report: SignalReport, *, soak_minutes: int | None = None) -> SignalReportCheck:
        return SignalReportCheck.objects.for_team(report.team_id).create(
            team_id=report.team_id,
            report=report,
            title="Verify the implementation",
            kind=SignalReportCheck.Kind.AGENT,
            config={},
            soak_minutes=soak_minutes,
            next_run_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )

    def _create_report(
        self,
        *,
        team: Team | None = None,
        report_status: str = SignalReport.Status.READY,
        title: str = "Test report",
    ) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=report_status,
            title=title,
            summary="Test summary",
            signal_count=1,
            total_weight=1,
        )

    def _claim_url(self, report: SignalReport) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report.id}/claim/"

    def _list_url(self, **query: str) -> str:
        suffix = "&".join(f"{key}={value}" for key, value in query.items())
        return f"/api/projects/{self.team.id}/signals/reports/{'?' + suffix if suffix else ''}"

    @staticmethod
    def _agent_headers(name: str) -> dict[str, str]:
        return {"X-PostHog-Client": "mcp", "X-Posthog-Mcp-Client-Name": name}

    def test_user_claim_returns_assignment_and_writes_activity(self):
        report = self._create_report()

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assignment = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert assignment is not None
        assert assignment.actor_kind == SignalActorKind.USER
        assert assignment.actor_user_id == self.user.id
        assert assignment.actor_task_id is None
        assert assignment.actor_agent is None
        assert assignment.claimed_at is not None
        assert response.json()["work_state"] == "working"
        assert response.json()["assignee"]["kind"] == SignalActorKind.USER
        assert response.json()["assignee"]["user"]["id"] == self.user.id

        log = ActivityLog.objects.get(
            team_id=self.team.id,
            scope="SignalReport",
            item_id=str(report.id),
            activity="assignment_changed",
        )
        assert log.detail is not None
        assert log.detail["changes"][0]["field"] == "assignee"
        assert log.detail["changes"][0]["before"] is None
        assert log.detail["changes"][0]["after"]["kind"] == SignalActorKind.USER

    def test_identical_claim_is_idempotent(self):
        report = self._create_report()
        self.client.post(self._claim_url(report), data={}, format="json")
        initial_claim = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert initial_claim is not None
        claimed_at = initial_claim.claimed_at

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assignment = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert assignment is not None
        assert assignment.claimed_at == claimed_at
        assert (
            ActivityLog.objects.filter(
                team_id=self.team.id,
                scope="SignalReport",
                item_id=str(report.id),
                activity="assignment_changed",
            ).count()
            == 1
        )

    def test_external_agent_explicitly_takes_over_claim(self):
        report = self._create_report()
        self.client.post(
            self._claim_url(report),
            data={},
            format="json",
            headers=self._agent_headers("claude-code"),
        )

        response = self.client.post(
            self._claim_url(report),
            data={"takeover": True},
            format="json",
            headers=self._agent_headers("codex"),
        )

        assert response.status_code == status.HTTP_200_OK
        assignment = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert assignment is not None
        assert assignment.actor_kind == SignalActorKind.AGENT
        assert assignment.actor_user_id == self.user.id
        assert assignment.actor_task_id is None
        assert assignment.actor_agent == "codex"
        logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="SignalReport",
            item_id=str(report.id),
            activity="assignment_changed",
        ).order_by("created_at")
        assert logs.count() == 2
        takeover = logs.last()
        assert takeover is not None and takeover.detail is not None
        change = takeover.detail["changes"][0]
        assert change["before"]["agent"] == "claude-code"
        assert change["after"]["agent"] == "codex"

    @parameterized.expand(
        [
            ("expected_claim", True, status.HTTP_200_OK, SignalActorKind.USER),
            ("stale_claim", False, status.HTTP_409_CONFLICT, SignalActorKind.AGENT),
        ]
    )
    def test_takeover_claim_id_guards_against_stale_reads(
        self, _name: str, expect_current_claim: bool, expected_status: int, expected_kind: str
    ):
        report = self._create_report()
        agent_claim = self.client.post(
            self._claim_url(report), data={}, format="json", headers=self._agent_headers("codex")
        ).json()["assignee"]["claim_id"]

        response = self.client.post(
            self._claim_url(report),
            data={
                "takeover": True,
                "takeover_claim_id": agent_claim if expect_current_claim else "00000000-0000-0000-0000-000000000001",
            },
            format="json",
        )

        assert response.status_code == expected_status
        assignment = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert assignment is not None
        assert assignment.actor_kind == expected_kind

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository", return_value=None)
    def test_additive_pr_updates_and_stale_claims(self, _integration):
        report = self._create_report()
        first = self.client.post(
            self._claim_url(report), {"pull_requests": ["https://github.com/example/app/pull/1"]}, format="json"
        )
        assert first.status_code == 200
        claim_id = first.json()["assignee"]["claim_id"]
        attached = first.json()["pull_requests"][0]
        assert attached["claim_id"] == claim_id
        assert attached["attached_at"] is not None
        assert attached["attached_by"]["kind"] == "user"
        assert attached["attached_by"]["user"]["id"] == self.user.id
        payload = {
            "claim_id": claim_id,
            "pull_requests": ["https://github.com/example/app/pull/1", "https://github.com/example/sdk/pull/2"],
        }
        for _ in range(2):
            response = self.client.post(self._claim_url(report), payload, format="json")
            assert response.status_code == 200
            assert len(response.json()["pull_requests"]) == 2
        assert SignalReportArtefact.objects.filter(report=report, type="pull_request").count() == 2
        assert SignalReportArtefact.objects.filter(report=report, type="work_claim").count() == 1
        from products.signals.backend.serializers import SignalReportSerializer

        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=report,
            pr_url="https://github.com/example/app/pull/1",
            repository="example/app",
            pr_number=1,
            pr_state="merged",
            pr_merged=True,
        )
        serialized = SignalReportSerializer(report).data
        assert serialized["implementation_pr_merged"] is False
        assert serialized["implementation_pr_state"] == "unknown"
        assert serialized["work_state"] == "in_review"
        assert len(serialized["pull_requests"]) == 2
        note_url = f"/api/projects/{self.team.id}/signals/reports/{report.id}/artefacts/"
        note = self.client.post(
            note_url,
            {"artefact_type": "note", "content": {"note": "Updated the parser"}, "claim_id": claim_id},
            format="json",
        )
        assert note.status_code == 201
        assert note.json()["claim_id"] == claim_id
        denied = self.client.post(self._claim_url(report), {}, format="json", headers=self._agent_headers("other"))
        assert denied.status_code == 409
        takeover = self.client.post(
            self._claim_url(report), {"takeover": True}, format="json", headers=self._agent_headers("other")
        )
        assert takeover.status_code == 200
        assert takeover.json()["assignee"]["claim_id"] != claim_id
        assert takeover.json()["pull_requests"][0]["attached_by"] == attached["attached_by"]
        assert takeover.json()["pull_requests"][0]["claim_id"] == claim_id
        stale = self.client.post(self._claim_url(report), payload, format="json")
        assert stale.status_code == 409
        assert (
            self.client.post(
                note_url,
                {"artefact_type": "note", "content": {"note": "Stale work"}, "claim_id": claim_id},
                format="json",
            ).status_code
            == 409
        )
        for artefact in SignalReportArtefact.objects.filter(
            report=report, type__in=["work_claim", "work_release", "pull_request"]
        ):
            assert self.client.delete(f"{note_url}{artefact.id}/").status_code == 400
        assert SignalReportArtefact.objects.filter(report=report, type="work_release", claim_id=claim_id).count() == 1
        assert SignalReportArtefact.objects.filter(report=report, type="pull_request", claim_id=claim_id).count() == 2

    @parameterized.expand(
        [
            ("all_closed", "closed", "closed", "suppressed", False, True, False),
            ("one_merged", "merged", "closed", "resolved", False, True, False),
            ("all_merged", "merged", "merged", "resolved", False, True, False),
            ("no_checks_without_merge_time", "merged", "closed", "resolved", False, True, True),
            ("unknown", "merged", "unknown", "ready", True, True, False),
            ("draft", "merged", "draft", "ready", True, True, False),
            ("monitoring", "merged", "closed", "monitoring", True, True, False),
            ("latest_merge", "merged", "merged", "monitoring", True, True, False),
            ("disabled", "merged", "merged", "resolved", True, False, False),
            ("missing_merge_time", "merged", "closed", "ready", True, True, True),
        ]
    )
    @patch("products.signals.backend.report_content_gates.feature_enabled_or_false")
    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository", return_value=None)
    def test_stack_completion_waits_for_all_prs(
        self,
        _name: str,
        first_state: str,
        last_state: str,
        expected: str,
        with_check: bool,
        enabled: bool,
        missing_time: bool,
        _integration: MagicMock,
        flag: MagicMock,
    ) -> None:
        flag.return_value = enabled
        first_merge = timezone.now() - timedelta(hours=2)
        last_merge = first_merge + timedelta(hours=1)
        report = self._create_report()
        check = self._create_check(report) if with_check else None
        response = self.client.post(
            self._claim_url(report),
            {
                "pull_requests": [
                    "https://github.com/example/app/pull/1",
                    "https://github.com/example/sdk/pull/2",
                ]
            },
            format="json",
        )
        assert response.status_code == 200
        update_assignments_for_pull_request(
            team_ids=[self.team.id],
            repository="example/app",
            pr_number=1,
            pr_state=first_state,
            merged_at=first_merge if first_state == "merged" and not missing_time else None,
        )
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        for retry_number in range(2):
            update_assignments_for_pull_request(
                team_ids=[self.team.id],
                repository="example/sdk",
                pr_number=2,
                pr_state=last_state,
                merged_at=last_merge + timedelta(minutes=retry_number) if last_state == "merged" else None,
            )
        report.refresh_from_db()
        assert report.status == expected
        attempts = SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(report_id=report.id)
        if expected == SignalReport.Status.MONITORING:
            assert check is not None
            attempt = attempts.get()
            assert list(attempt.check_versions) == [str(check.id)]
            assert report.monitoring_started_at == (last_merge if last_state == "merged" else first_merge)
            assert attempt.monitoring_started_at == report.monitoring_started_at
        else:
            assert not attempts.exists()
        if missing_time and with_check:
            update_assignments_for_pull_request(
                team_ids=[self.team.id],
                repository="example/app",
                pr_number=1,
                pr_state="merged",
                merged_at=first_merge,
            )
            report.refresh_from_db()
            assert report.status == SignalReport.Status.MONITORING
            assert report.monitoring_started_at == first_merge
            assert attempts.count() == 1
        if expected != SignalReport.Status.READY:
            retry = self.client.post(
                self._claim_url(report),
                {
                    "claim_id": response.json()["assignee"]["claim_id"],
                    "pull_requests": ["https://github.com/example/app/pull/1", "https://github.com/example/sdk/pull/2"],
                },
                format="json",
            )
            assert retry.status_code == 200
            assert SignalReportArtefact.objects.filter(report=report, type="pull_request").count() == 2

    @parameterized.expand(
        [
            ("monitoring", "monitoring", False),
            ("archived", "suppressed", False),
            ("reopened", "ready", False),
            ("reopened_missing_time", "ready", True),
        ]
    )
    @patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository", return_value=None)
    def test_old_merge_preserves_an_existing_period_and_lifecycle_decisions(
        self, _name: str, current_status: str, missing_time: bool, _integration: MagicMock, _flag: MagicMock
    ) -> None:
        report = self._create_report()
        check = self._create_check(report)
        assert (
            self.client.post(
                self._claim_url(report), {"pr_url": "https://github.com/example/app/pull/1"}, format="json"
            ).status_code
            == 200
        )
        started_at = timezone.now() - timedelta(hours=2)
        attempt = complete_implementation(team_id=self.team.id, report_id=report.id, monitoring_started_at=started_at)
        assert attempt is not None
        report.refresh_from_db()
        if current_status != SignalReport.Status.MONITORING:
            report.save(update_fields=report.transition_to(SignalReport.Status(current_status)))
        if missing_time:
            check.status = SignalReportCheck.Status.CANCELLED
            check.save(update_fields=["status"])

        update_assignments_for_pull_request(
            team_ids=[self.team.id],
            repository="example/app",
            pr_number=1,
            pr_state="merged",
            merged_at=None if missing_time else started_at,
        )

        report.refresh_from_db()
        assert report.status == current_status
        assert report.monitoring_started_at == (None if current_status == "ready" else started_at)
        assert list(SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(report=report)) == [attempt]

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_attaching_a_partly_merged_stack_does_not_finish_early(self, integration):
        github = integration.return_value
        github.get_pull_request.side_effect = [
            {"success": True, "state": "closed", "merged": True},
            {"success": True, "state": "open", "merged": False},
        ]
        report = self._create_report()
        response = self.client.post(
            self._claim_url(report),
            {
                "pull_requests": ["https://github.com/example/app/pull/1", "https://github.com/example/app/pull/2"],
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == SignalReport.Status.READY
        assert response.json()["implementation_pr_url"].endswith("/2")
        assert response.json()["work_state"] == "in_review"

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository", return_value=None)
    def test_shared_pr_webhook_is_team_scoped_and_merge_is_terminal(self, _integration):
        reports = [self._create_report(), self._create_report()]
        for report in reports:
            response = self.client.post(
                self._claim_url(report), {"pull_requests": ["https://github.com/example/app/pull/1"]}, format="json"
            )
            assert response.status_code == 200
        assert SignalReportPullRequest.objects.for_team(self.team.id).count() == 1
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_pr = SignalReportPullRequest.objects.for_team(other_team.id).create(
            team_id=other_team.id, repository="example/app", number=1, url="https://github.com/example/app/pull/1"
        )
        for state in ["merged", "open", "closed"]:
            update_assignments_for_pull_request(
                team_ids=[self.team.id], repository="example/app", pr_number=1, pr_state=state
            )
        for report in reports:
            report.refresh_from_db()
            assert report.status == SignalReport.Status.RESOLVED
        other_pr.refresh_from_db()
        assert other_pr.state == "unknown"
        assert SignalReportPullRequest.objects.for_team(self.team.id).get().state == "merged"

    def test_generic_mcp_client_name_is_used_when_registration_name_is_missing(self):
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={},
            format="json",
            headers={"X-PostHog-Client": "mcp"},
        )

        assert response.status_code == status.HTTP_200_OK
        assignment = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert assignment is not None
        assert assignment.actor_kind == SignalActorKind.AGENT
        assert assignment.actor_agent == "mcp"

    @parameterized.expand(
        [
            ("codex", "Alex's Codex"),
            ("claude-code", "Alex's Claude Code"),
            ("mcp", "Alex's agent"),
        ]
    )
    def test_external_claim_display_name_is_recorded_once(self, client_name, expected):
        self.user.first_name = "Alex"
        self.user.save(update_fields=["first_name"])
        report = self._create_report()
        response = self.client.post(
            self._claim_url(report), data={}, format="json", headers=self._agent_headers(client_name)
        )
        assert response.status_code == status.HTTP_200_OK
        claim = SignalReportArtefact.objects.get(report=report, type="work_claim")
        assert json.loads(claim.content)["display_name"] == expected
        self.user.first_name = "Renamed"
        self.user.save(update_fields=["first_name"])
        again = self.client.post(
            self._claim_url(report), data={}, format="json", headers=self._agent_headers(client_name)
        )
        claim.refresh_from_db()
        assert json.loads(claim.content)["display_name"] == expected
        assert again.json()["assignee"]["claim_id"] == response.json()["assignee"]["claim_id"]

    @parameterized.expand(
        [
            ("research", "Research agent"),
            ("implementation", "Implementation agent"),
            ("repo_selection", "Repository selection agent"),
            ("scout:checkout", "Scout checkout"),
            (None, "PostHog agent"),
        ]
    )
    def test_internal_claim_display_name_uses_phase(self, phase, expected):
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team, created_by=self.user, title="Agent task", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        TaskRun.objects.create(team=self.team, task=task, state={"ai_stage": phase})
        report = self._create_report()
        response = self.client.post(
            self._claim_url(report), data={}, format="json", headers={"X-PostHog-Task-Id": str(task.id)}
        )
        assert response.status_code == status.HTTP_200_OK
        claim = SignalReportArtefact.objects.get(report=report, type="work_claim")
        assert json.loads(claim.content)["display_name"] == expected

    def test_claimants_own_task_works_under_their_claim(self):
        Task = apps.get_model("tasks", "Task")
        report = self._create_report()
        claim_id = self.client.post(self._claim_url(report), data={}, format="json").json()["assignee"]["claim_id"]
        task = Task.objects.create(
            team=self.team, created_by=self.user, title="Signal task", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        task_headers = {"X-PostHog-Task-Id": str(task.id)}

        resumed = self.client.post(
            self._claim_url(report), data={"claim_id": claim_id}, format="json", headers=task_headers
        )
        note = self.client.post(
            f"/api/projects/{self.team.id}/signals/reports/{report.id}/artefacts/",
            {"artefact_type": "note", "content": {"note": "Opened the PR"}, "claim_id": claim_id},
            format="json",
            headers=task_headers,
        )
        release = self.client.post(self._claim_url(report), data={"release": True}, format="json", headers=task_headers)

        assert resumed.status_code == status.HTTP_200_OK
        assert resumed.json()["assignee"]["kind"] == SignalActorKind.USER
        assert note.status_code == status.HTTP_201_CREATED
        assert note.json()["claim_id"] == claim_id
        assert release.status_code == status.HTTP_409_CONFLICT

    def test_internal_task_claim_uses_task_attribution(self):
        Task = apps.get_model("tasks", "Task")
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Signal task",
            description="Implement the report",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={},
            format="json",
            headers={"X-PostHog-Task-Id": str(task.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assignment = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert assignment is not None
        assert assignment.actor_kind == SignalActorKind.TASK
        assert assignment.actor_user_id is None
        assert assignment.actor_task_id == task.id
        assert assignment.actor_agent is None
        assert response.json()["assignee"]["task_id"] == str(task.id)

        TaskRun = apps.get_model("tasks", "TaskRun")
        pr_urls = ["https://github.com/example/app/pull/1", "https://github.com/example/app/pull/2"]
        with patch("products.signals.backend.tasks.link_report_tracker_issues.delay") as link_tracker:
            with self.captureOnCommitCallbacks(execute=True):
                TaskRun.objects.create(
                    team=self.team,
                    task=task,
                    status=TaskRun.Status.COMPLETED,
                    output={"pr_url": pr_urls[0], "pr_urls": pr_urls},
                )
                link_tracker.assert_not_called()
            assert link_tracker.call_args_list == [
                call(team_id=self.team.id, task_id=str(task.id), pr_url=url) for url in pr_urls
            ]
        assert set(
            SignalReportArtefact.objects.filter(report=report, type="pull_request").values_list(
                "pull_request__url", flat=True
            )
        ) == set(pr_urls)

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_connected_pull_request_details_are_fetched(self, mock_first_for_repository):
        github = MagicMock()
        github.get_pull_request.return_value = {
            "success": True,
            "url": "https://github.com/PostHog/posthog/pull/123",
            "state": "open",
            "draft": False,
            "merged": False,
        }
        mock_first_for_repository.return_value = github
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_first_for_repository.assert_called_once_with(
            self.team.id, "PostHog/posthog", source="signals_reviewers", priority=Priority.NORMAL
        )
        github.get_pull_request.assert_called_once_with("PostHog/posthog", 123)
        pr = SignalReportPullRequest.objects.for_team(self.team.id).get(repository="posthog/posthog", number=123)
        assert pr.repository == "posthog/posthog"
        assert pr.number == 123
        assert pr.state == SignalReportAssignment.PrState.OPEN
        assert pr.state != "merged"
        assert response.json()["work_state"] == "in_review"

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_refresh_shared_pr_reconciles_other_reports_after_entire_stack_is_attached(self, integration):
        github = integration.return_value
        github.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        reports = [self._create_report() for _ in range(2)]
        shared = "https://github.com/example/app/pull/1"
        for report in reports:
            assert (
                self.client.post(self._claim_url(report), {"pull_requests": [shared]}, format="json").status_code == 200
            )
        github.get_pull_request.side_effect = [
            {"success": True, "state": "closed", "merged": True},
            {"success": True, "state": "open", "merged": False},
        ]
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self._claim_url(reports[0]),
                {"pull_requests": [shared, "https://github.com/example/app/pull/2"]},
                format="json",
            )
        assert response.status_code == 200
        for report in reports:
            report.refresh_from_db()
        assert reports[0].status == SignalReport.Status.READY
        assert reports[1].status == SignalReport.Status.RESOLVED

    def test_releasing_latest_claim_does_not_restore_legacy_owner(self):
        report = self._create_report()
        legacy = SignalReportAssignment.all_teams.create(
            team=self.team,
            report=report,
            actor_kind="user",
            actor_user=self.user,
        )
        first = self.client.post(self._claim_url(report), {}, format="json")
        assert first.status_code == 200
        assert first.json()["assignee"]["claim_id"] == str(legacy.id)
        released = self.client.post(self._claim_url(report), {"release": True}, format="json")
        assert released.status_code == 200
        assert get_active_claim(team_id=self.team.id, report_id=report.id) is None
        unclaimed = self.client.get(self._list_url(unclaimed="true"))
        assert str(report.id) in [item["id"] for item in unclaimed.json()["results"]]
        assert self.client.get(self._list_url(assignee="me")).json()["results"] == []
        again = self.client.post(self._claim_url(report), {}, format="json")
        assert again.status_code == 200
        assert again.json()["assignee"]["claim_id"] != str(legacy.id)
        legacy.refresh_from_db()
        assert legacy.actor_user_id == self.user.id

    @parameterized.expand([("no_checks", False), ("checks", True)])
    @patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_merged_pull_request_completes_implementation_on_claim(
        self, _name: str, with_check: bool, mock_first_for_repository: MagicMock, _flag: MagicMock
    ) -> None:
        merged_at = timezone.now() - timedelta(hours=1)
        github = MagicMock()
        github.get_pull_request.return_value = {
            "success": True,
            "url": "https://github.com/PostHog/posthog/pull/123",
            "state": "closed",
            "draft": False,
            "merged": True,
            "merged_at": merged_at.isoformat(),
        }
        mock_first_for_repository.return_value = github
        report = self._create_report()
        if with_check:
            self._create_check(report, soak_minutes=60)

        response = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assert report.status == (SignalReport.Status.MONITORING if with_check else SignalReport.Status.RESOLVED)
        assert report.monitoring_started_at == (merged_at if with_check else None)
        pr = SignalReportPullRequest.objects.for_team(self.team.id).get(repository="posthog/posthog", number=123)
        assert pr.state == SignalReportAssignment.PrState.MERGED
        assert pr.state == "merged"
        assert pr.merged_at == merged_at
        assert response.json()["work_state"] == "done"

    @patch(
        "products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository",
        return_value=None,
    )
    def test_unconnected_pull_request_is_allowed_with_unknown_state(self, mock_first_for_repository):
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_first_for_repository.assert_called_once_with(
            self.team.id, "PostHog/posthog", source="signals_reviewers", priority=Priority.NORMAL
        )
        pr = SignalReportPullRequest.objects.for_team(self.team.id).get(repository="posthog/posthog", number=123)
        assert pr.repository == "posthog/posthog"
        assert pr.number == 123
        assert pr.state == SignalReportAssignment.PrState.UNKNOWN
        assert pr.state != "merged"

    @parameterized.expand(
        [
            ("claiming_agent", "claude-code", False, False, status.HTTP_200_OK),
            ("responsible_user", None, False, False, status.HTTP_200_OK),
            ("responsible_user_with_claim_id", None, False, True, status.HTTP_200_OK),
            ("different_agent", "codex", False, True, status.HTTP_409_CONFLICT),
            ("different_user", None, True, True, status.HTTP_409_CONFLICT),
        ]
    )
    def test_only_current_actor_or_responsible_user_can_release_and_pr_is_preserved(
        self, _name: str, agent: str | None, different_user: bool, include_claim_id: bool, expected_status: int
    ) -> None:
        report = self._create_report()
        claim = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
            headers=self._agent_headers("claude-code"),
        )
        assert claim.status_code == status.HTTP_200_OK

        if different_user:
            other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
            self.client.force_login(other_user)

        released = self.client.post(
            self._claim_url(report),
            data={"release": True, **({"claim_id": claim.json()["assignee"]["claim_id"]} if include_claim_id else {})},
            format="json",
            headers=self._agent_headers(agent) if agent else {},
        )

        assert released.status_code == expected_status
        assignment = get_active_claim(team_id=self.team.id, report_id=report.id)
        if expected_status == status.HTTP_409_CONFLICT:
            assert assignment is not None
            assert str(assignment.claim_id) == claim.json()["assignee"]["claim_id"]
            assert not SignalReportArtefact.objects.filter(report=report, type="work_release").exists()
            return
        assert assignment is None
        assert released.json()["implementation_pr_url"] == "https://github.com/PostHog/posthog/pull/123"
        assert released.json()["implementation_pr_state"] == "unknown"
        assert released.json()["work_state"] == "in_review"
        assert released.json()["assignee"] is None

    @parameterized.expand(
        [
            ("negative_number", "https://github.com/PostHog/posthog/pull/-5"),
            ("zero_number", "https://github.com/PostHog/posthog/pull/0"),
            ("number_above_bigint", "https://github.com/PostHog/posthog/pull/99999999999999999999999"),
            ("overlong_repository", f"https://github.com/{'o' * 300}/posthog/pull/5"),
        ]
    )
    def test_unstorable_pull_request_url_is_rejected(self, _name: str, pr_url: str):
        report = self._create_report()

        response = self.client.post(self._claim_url(report), data={"pr_url": pr_url}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "pr_url" in response.json()["attr"]
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    def test_release_and_pr_url_cannot_be_combined(self):
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={"release": True, "pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY),
            ("pending_input", SignalReport.Status.PENDING_INPUT),
            ("potential", SignalReport.Status.POTENTIAL),
            ("candidate", SignalReport.Status.CANDIDATE),
            ("in_progress", SignalReport.Status.IN_PROGRESS),
            ("failed", SignalReport.Status.FAILED),
        ]
    )
    def test_claimable_report_statuses(self, _name: str, report_status: str):
        report = self._create_report(report_status=report_status)

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert get_active_claim(team_id=self.team.id, report_id=report.id) is not None
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    @parameterized.expand(
        [
            ("resolved", SignalReport.Status.RESOLVED, False, "resolved"),
            ("monitoring_enabled", SignalReport.Status.MONITORING, True, "monitoring"),
            ("monitoring_disabled", SignalReport.Status.MONITORING, False, "resolved"),
            ("monitoring_unavailable", SignalReport.Status.MONITORING, RuntimeError("flag unavailable"), "resolved"),
        ]
    )
    def test_resolved_report_cannot_be_claimed(
        self, _name: str, report_status: str, flag_result: bool | Exception, expected_status: str
    ) -> None:
        report = self._create_report(report_status=report_status)

        with patch(
            "products.signals.backend.report_content_gates.feature_enabled_or_false",
            return_value=flag_result if isinstance(flag_result, bool) else False,
            side_effect=flag_result if isinstance(flag_result, Exception) else None,
        ):
            response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert f"status '{expected_status}'" in response.json()["detail"]
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    def test_suppressed_report_cannot_be_claimed(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    def test_claim_cannot_cross_team_boundary(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        report = self._create_report(team=other_team)

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    @parameterized.expand([("live_filters", False), ("cached_columns", True)])
    def test_unclaimed_filter_excludes_claims_and_open_prs(self, _name: str, cached: bool) -> None:
        unclaimed = self._create_report(title="Unclaimed")
        claimed = self._create_report(title="Claimed")
        in_review = self._create_report(title="In review")
        self.client.post(self._claim_url(claimed), data={}, format="json")
        with self.captureOnCommitCallbacks(execute=True):
            SignalReportAssignment.all_teams.create(
                team=self.team,
                report=in_review,
                pr_url="https://github.com/PostHog/posthog/pull/123",
                repository="posthog/posthog",
                pr_number=123,
                pr_state=SignalReportAssignment.PrState.OPEN,
            )
            merged_assignment = self._create_report(title="Merged assignment")
            SignalReportAssignment.all_teams.create(
                team=self.team,
                report=merged_assignment,
                pr_url="https://github.com/PostHog/posthog/pull/124",
                repository="posthog/posthog",
                pr_number=124,
                pr_state=SignalReportAssignment.PrState.MERGED,
                pr_merged=True,
            )
            linked = {}
            for number, state in [
                (125, SignalReportPullRequest.State.OPEN),
                (126, SignalReportPullRequest.State.MERGED),
            ]:
                report = self._create_report(title=f"Linked {state}")
                pr = SignalReportPullRequest.objects.create(
                    team=self.team,
                    repository="posthog/posthog",
                    number=number,
                    url=f"https://github.com/PostHog/posthog/pull/{number}",
                    state=state,
                )
                SignalReportArtefact.objects.create(
                    team=self.team, report=report, type=SignalReportArtefact.ArtefactType.PULL_REQUEST, pull_request=pr
                )
                linked[state] = report

        with patch("products.signals.backend.views.organization_inbox_cached_filters_enabled", return_value=cached):
            response = self.client.get(self._list_url(unclaimed="true"))

        assert response.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in response.json()["results"]}
        assert str(unclaimed.id) in ids
        assert str(claimed.id) not in ids
        assert str(in_review.id) not in ids
        assert str(merged_assignment.id) in ids
        assert str(linked[SignalReportPullRequest.State.OPEN].id) not in ids
        assert str(linked[SignalReportPullRequest.State.MERGED].id) in ids

    def test_assignee_me_matches_exact_external_agent(self):
        mine = self._create_report(title="Mine")
        other = self._create_report(title="Other")
        self.client.post(
            self._claim_url(mine),
            data={},
            format="json",
            headers=self._agent_headers("codex"),
        )
        self.client.post(
            self._claim_url(other),
            data={},
            format="json",
            headers=self._agent_headers("claude-code"),
        )

        response = self.client.get(
            self._list_url(assignee="me"),
            headers=self._agent_headers("codex"),
        )

        assert response.status_code == status.HTTP_200_OK
        assert {row["id"] for row in response.json()["results"]} == {str(mine.id)}

    def test_assignee_mine_matches_claims_by_the_user_and_their_agents_but_not_their_tasks(self):
        Task = apps.get_model("tasks", "Task")
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
        own_task = Task.objects.create(
            team=self.team, created_by=self.user, title="Own task", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        teammate_task = Task.objects.create(
            team=self.team, created_by=teammate, title="Teammate task", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        mine = [self._create_report(title=title) for title in ("By me", "By my agent")]
        theirs = [self._create_report(title=title) for title in ("By teammate", "By teammate task", "By my task")]
        for report, headers in [
            (mine[0], {}),
            (mine[1], self._agent_headers("codex")),
            (theirs[2], {"X-PostHog-Task-Id": str(own_task.id)}),
            (theirs[1], {"X-PostHog-Task-Id": str(teammate_task.id)}),
        ]:
            assert self.client.post(self._claim_url(report), data={}, format="json", headers=headers).status_code == 200
        self.client.force_login(teammate)
        assert self.client.post(self._claim_url(theirs[0]), data={}, format="json").status_code == 200
        self.client.force_login(self.user)

        response = self.client.get(self._list_url(assignee="mine"))

        assert response.status_code == status.HTTP_200_OK
        rows = response.json()["results"]
        assert {row["id"] for row in rows} == {str(report.id) for report in mine}
        assert {row["assignee"]["responsible_user"]["id"] for row in rows} == {self.user.id}

    def test_responsible_users_resolves_task_claims_in_fixed_queries(self):
        Task = apps.get_model("tasks", "Task")
        reports = [self._create_report(title=f"Task report {i}") for i in range(3)]
        for report in reports:
            task = Task.objects.create(
                team=self.team, created_by=self.user, title="Task", origin_product=Task.OriginProduct.SIGNAL_REPORT
            )
            headers = {"X-PostHog-Task-Id": str(task.id)}
            assert self.client.post(self._claim_url(report), data={}, format="json", headers=headers).status_code == 200
        claims = get_active_claims(team_id=self.team.id, report_ids=[str(report.id) for report in reports])

        with self.assertNumQueries(2):
            users = responsible_users(claims.values())

        assert len(users) == len(reports)
        assert {user.id for user in users.values()} == {self.user.id}

    def _bulk_claim_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/bulk_claim/"

    def test_bulk_claim_reports_each_id_without_reaching_other_teams(self):
        ready = self._create_report()
        dismissed = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        foreign = self._create_report(team=other_team)
        unknown = "00000000-0000-0000-0000-000000000000"

        response = self.client.post(
            self._bulk_claim_url(),
            data={"ids": [str(ready.id), str(dismissed.id), str(foreign.id), unknown, str(ready.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert [(row["id"], row["outcome"]) for row in body["results"]] == [
            (str(ready.id), "claimed"),
            (str(dismissed.id), "conflict"),
            (str(foreign.id), "not_found"),
            (unknown, "not_found"),
        ]
        assert (body["claimed_count"], body["conflict_count"], body["not_found_count"]) == (1, 1, 2)
        claim = get_active_claim(team_id=self.team.id, report_id=ready.id)
        assert claim is not None and claim.actor_user_id == self.user.id
        assert get_active_claim(team_id=other_team.id, report_id=foreign.id) is None

    @parameterized.expand(
        [
            ("an agent, without takeover", "agent", False, "conflict", SignalActorKind.AGENT),
            ("an agent, with takeover", "agent", True, "claimed", SignalActorKind.USER),
            ("a person, with takeover", "person", True, "conflict", SignalActorKind.USER),
        ]
    )
    def test_bulk_claim_takes_over_only_agent_claims_on_request(
        self, _name: str, holder: str, takeover: bool, outcome: str, kind_after: str
    ) -> None:
        report = self._create_report()
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
        if holder == "agent":
            self.client.post(self._claim_url(report), data={}, format="json", headers=self._agent_headers("codex"))
        else:
            self.client.force_login(teammate)
            self.client.post(self._claim_url(report), data={}, format="json")
            self.client.force_login(self.user)

        response = self.client.post(
            self._bulk_claim_url(), data={"ids": [str(report.id)], "takeover_agent_claims": takeover}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["results"][0]["outcome"] == outcome
        claim = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert claim is not None and claim.actor_kind == kind_after
        assert claim.actor_user_id == (teammate.id if holder == "person" else self.user.id)

    def test_claim_with_a_pull_request_logs_the_implementation_pr_change(self):
        report = self._create_report()
        pr_url = "https://github.com/example/app/pull/7"

        response = self.client.post(self._claim_url(report), data={"pr_url": pr_url}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        log = ActivityLog.objects.get(
            team_id=self.team.id, scope="SignalReport", item_id=str(report.id), activity="assignment_changed"
        )
        assert log.detail is not None
        pr_change = next(change for change in log.detail["changes"] if change["field"] == "implementation_pr")
        assert pr_change["before"] is None
        assert pr_change["after"]["url"] == pr_url

    def test_bulk_claim_adds_a_fixed_number_of_queries_per_report(self):
        def queries_for(count: int) -> int:
            ids = [str(self._create_report(title=f"Report {i}").id) for i in range(count)]
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.post(self._bulk_claim_url(), data={"ids": ids}, format="json")
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["claimed_count"] == count
            return len(ctx.captured_queries)

        # The first call fills caches the later ones reuse, so it is not measured.
        queries_for(1)
        for_two, for_three, for_four = (queries_for(n) for n in (2, 3, 4))

        per_report = for_three - for_two
        assert for_four - for_three == per_report
        assert per_report <= 11
        assert for_two - 2 * per_report <= 15

    def test_claimed_report_remains_in_default_actionable_list(self):
        report = self._create_report()
        self.client.post(self._claim_url(report), data={}, format="json")

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        row = next(row for row in response.json()["results"] if row["id"] == str(report.id))
        assert row["work_state"] == "working"
