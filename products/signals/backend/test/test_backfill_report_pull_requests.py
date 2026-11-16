from datetime import UTC, datetime, timedelta
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.utils import timezone

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportPullRequest,
    SignalReportTask,
)
from products.signals.backend.report_assignments import update_assignments_for_pull_request
from products.tasks.backend.models import Task, TaskRun


class TestBackfillReportPullRequests(BaseTest):
    @patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
    def test_repairs_task_history_merge_time_before_starting_monitoring(self, _flag: MagicMock) -> None:
        from products.signals.backend.tasks import refresh_pull_request_review_decision

        report = SignalReport.objects.create(team=self.team, status="ready", title="Report", summary="Summary")
        task = Task.objects.create(team=self.team, title="Implementation", description="", origin_product="signals")
        SignalReportTask.objects.create(team=self.team, report=report, task=task, relationship="implementation")
        run = TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.COMPLETED)
        TaskRun.objects.filter(id=run.id).update(
            output={"pr_url": "https://github.com/example/app/pull/1", "pr_state": "merged", "pr_merged": True}
        )
        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=report,
            pr_url="https://github.com/example/app/pull/2",
            repository="example/app",
            pr_number=2,
            pr_state="open",
        )
        check = SignalReportCheck.objects.for_team(self.team.id).create(
            team=self.team,
            report=report,
            title="Verify recovery",
            kind=SignalReportCheck.Kind.AGENT,
            config={"instructions": "Verify recovery", "skill_name": "verification"},
            soak_minutes=60,
            status=SignalReportCheck.Status.PENDING,
            next_run_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=7),
        )
        latest_merge = timezone.now() - timedelta(hours=1)
        github = MagicMock()
        github.get_pull_request.return_value = {
            "success": True,
            "merged": True,
            "merged_at": (latest_merge - timedelta(hours=1)).isoformat(),
        }
        github.get_pull_request_snapshot.return_value = {"success": True, "review_decision": "approved"}
        with (
            patch("products.signals.backend.tasks.refresh_pull_request_review_decision.delay") as refresh,
            patch("products.signals.backend.tasks.refresh_pull_request_participants.delay"),
            patch("products.signals.backend.tasks.assign_reviewers_on_implementation_pr.delay"),
            patch("products.signals.backend.tasks.send_pull_request_ready_push.delay"),
            patch("posthog.models.integration.GitHubIntegration.first_for_team_repository", return_value=github),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                update_assignments_for_pull_request(
                    team_ids=[self.team.id],
                    repository="example/app",
                    pr_number=2,
                    pr_state="merged",
                    merged_at=latest_merge,
                )
            report.refresh_from_db()
            assert report.status == "ready"
            refresh.assert_any_call(team_id=self.team.id, repository="example/app", pr_number=1)
            link = SignalReportArtefact.objects.get(report=report, type="pull_request", task=task)
            assert link.actor_kind == "task"
            assert not SignalReportArtefact.objects.filter(report=report, type="work_claim").exists()
            with self.captureOnCommitCallbacks(execute=True):
                refresh_pull_request_review_decision(team_id=self.team.id, repository="example/app", pr_number=1)

        completed = SignalReport.objects.get(id=report.id, team_id=self.team.id)
        assert completed.status == SignalReport.Status.MONITORING
        attempt = SignalReportMonitoringAttempt.objects.for_team(self.team.id).get(report=report)
        assert attempt.monitoring_started_at == latest_merge
        assert set(attempt.check_versions) == {str(check.id)}

    def test_refreshes_stored_review_decision(self) -> None:
        from products.signals.backend.tasks import refresh_pull_request_review_decision

        pr = SignalReportPullRequest.objects.for_team(self.team.id).create(
            team=self.team,
            repository="example/app",
            number=42,
            url="https://github.com/example/app/pull/42",
            state="open",
        )
        github = MagicMock()
        github.get_pull_request_snapshot.return_value = {"success": True, "review_decision": "approved"}

        with patch("posthog.models.integration.GitHubIntegration.first_for_team_repository", return_value=github):
            refresh_pull_request_review_decision(team_id=self.team.id, repository="example/app", pr_number=42)

        pr.refresh_from_db()
        assert pr.review_decision == "approved"

    def test_backfill_is_resumable_and_preserves_verified_state_and_ownership(self) -> None:
        reports = [
            SignalReport.objects.create(team=self.team, status="ready", title="Report", summary="Summary")
            for _ in range(4)
        ]
        active, released, task_report, deleted_principal = reports
        primary = "https://github.com/example/app/pull/1"
        assignment = SignalReportAssignment.all_teams.create(
            team=self.team,
            report=active,
            actor_kind="user",
            actor_user=self.user,
            pr_url=primary,
            repository="example/app",
            pr_number=1,
            pr_state="open",
        )
        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=released,
            pr_url=primary,
            repository="example/app",
            pr_number=1,
            pr_state="open",
        )
        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=deleted_principal,
            actor_kind="agent",
            actor_agent="example-agent",
            pr_url=primary,
            repository="example/app",
            pr_number=1,
            pr_state="open",
        )
        task = Task.objects.create(team=self.team, title="Implementation", description="", origin_product="signals")
        run = TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.COMPLETED)
        TaskRun.objects.filter(id=run.id).update(
            output={
                "pr_url": primary,
                "pr_state": "open",
                "pr_urls": [primary, "https://github.com/example/sdk/pull/2"],
            }
        )
        SignalReportTask.objects.create(team=self.team, report=task_report, task=task, relationship="implementation")
        with (
            patch("products.signals.backend.tasks.assign_reviewers_on_implementation_pr.delay") as reviewers,
            patch("products.signals.backend.tasks.send_pull_request_ready_push.delay") as ready_push,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                call_command("backfill_report_pull_requests", team_id=self.team.id, batch_size=1, stdout=StringIO())
            reviewers.assert_not_called()
            ready_push.assert_not_called()
        assignment.refresh_from_db()
        claim_id = SignalReportArtefact.objects.get(report=active, type="work_claim").id
        assert claim_id is not None
        assert assignment.actor_user_id == self.user.id
        assert SignalReportAssignment.all_teams.filter(report=task_report).count() == 0
        assert SignalReportPullRequest.objects.for_team(self.team.id).count() == 1
        assert (
            SignalReportArtefact.objects.filter(report=task_report, type="pull_request", actor_kind="task").count() == 0
        )
        assert SignalReportArtefact.objects.get(report=released, type="pull_request").actor_kind is None
        imported = SignalReportArtefact.objects.get(report=deleted_principal, type="pull_request")
        assert imported.actor_kind == "agent"
        assert imported.actor_agent == "example-agent"
        assert not SignalReportPullRequest.objects.for_team(self.team.id).filter(checked_at__isnull=False).exists()
        update_assignments_for_pull_request(
            team_ids=[self.team.id], repository="example/app", pr_number=1, pr_state="merged"
        )
        count = SignalReportArtefact.objects.filter(team=self.team).count()
        call_command(
            "backfill_report_pull_requests", team_id=self.team.id, batch_size=1, after=str(active.id), stdout=StringIO()
        )
        call_command("backfill_report_pull_requests", team_id=self.team.id, batch_size=1, stdout=StringIO())
        assert SignalReportArtefact.objects.filter(team=self.team).count() == count
        assert SignalReportPullRequest.objects.for_team(self.team.id).get(number=1).state == "merged"
        assignment.refresh_from_db()
        assert SignalReportArtefact.objects.get(report=active, type="work_claim").id == claim_id
        task_report.refresh_from_db()
        assert task_report.status == "ready"

    def test_reads_union_without_importing_task_history_and_webhook_updates_secondary_pr(self) -> None:
        from django.db import transaction

        from products.signals.backend.implementation_pr import (
            fetch_implementation_prs_for_reports,
            report_ids_for_implementation_pr,
        )
        from products.signals.backend.pull_requests import apply_report_completion, import_report_pull_requests

        report = SignalReport.objects.create(team=self.team, status="ready", title="Report", summary="Summary")
        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=report,
            pr_url="https://github.com/example/app/pull/1",
            repository="example/app",
            pr_number=1,
            pr_state="merged",
            pr_merged=True,
        )
        task = Task.objects.create(team=self.team, title="Implementation", description="", origin_product="signals")
        SignalReportTask.objects.create(team=self.team, report=report, task=task, relationship="implementation")
        run = TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.COMPLETED)
        TaskRun.objects.filter(id=run.id).update(
            output={"pr_urls": ["https://github.com/EXAMPLE/app/pull/1", "https://github.com/example/sdk/pull/2"]}
        )
        with transaction.atomic():
            import_report_pull_requests(report)
            apply_report_completion(report)
        merged_at = datetime(2026, 6, 11, 10, tzinfo=UTC)
        SignalReportPullRequest.objects.for_team(self.team.id).filter(number=1).update(
            review_decision="approved", merged_at=merged_at
        )
        report.refresh_from_db()
        assert report.status == "ready"
        prs = fetch_implementation_prs_for_reports([str(report.id)], team_id=self.team.id)[str(report.id)]
        assert len(prs) == 2
        assert prs[0].state == "merged"
        assert prs[1].task_id == str(task.id)
        assert prs[0].review_decision == "approved"
        assert prs[0].merged_at == merged_at
        assert (
            prs[1].id
            == fetch_implementation_prs_for_reports([str(report.id)], team_id=self.team.id)[str(report.id)][1].id
        )
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        from products.signals.backend.serializers import SignalReportPullRequestSerializer
        from products.signals.backend.views import SignalReportViewSet

        assert prs[1].id is not None

        view = SignalReportViewSet(request=Request(APIRequestFactory().get("/", {"pull_request_id": prs[1].id})))
        assert view._resolve_report_pr_reference(report) == ("example/sdk", 2)
        assert SignalReportPullRequestSerializer(prs[1]).data["attached_by"]["task_id"] == str(task.id)
        assert SignalReportPullRequestSerializer(prs[0]).data["review_decision"] == "approved"
        assert SignalReportPullRequestSerializer(prs[0]).data["merged_at"] == "2026-06-11T10:00:00Z"
        assert SignalReportArtefact.objects.filter(report=report, type="pull_request").count() == 1
        assert report_ids_for_implementation_pr(team_id=self.team.id, repository="example/sdk", pr_number=2) == [
            str(report.id)
        ]
        update_assignments_for_pull_request(
            team_ids=[self.team.id], repository="example/sdk", pr_number=2, pr_state="closed"
        )
        report.refresh_from_db()
        assert report.status == "resolved"
        assert view._resolve_report_pr_reference(report) == ("example/sdk", 2)
        assert len(fetch_implementation_prs_for_reports([str(report.id)], team_id=self.team.id)[str(report.id)]) == 2
