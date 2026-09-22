from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportPullRequest,
    SignalReportTask,
)
from products.signals.backend.report_assignments import update_assignments_for_pull_request
from products.tasks.backend.models import Task, TaskRun


class TestBackfillReportPullRequests(BaseTest):
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
        with patch("products.signals.backend.tasks.assign_reviewers_on_implementation_pr.delay") as reviewers:
            with self.captureOnCommitCallbacks(execute=True):
                call_command("backfill_report_pull_requests", team_id=self.team.id, batch_size=1, stdout=StringIO())
            reviewers.assert_not_called()
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
        report.refresh_from_db()
        assert report.status == "ready"
        prs = fetch_implementation_prs_for_reports([str(report.id)], team_id=self.team.id)[str(report.id)]
        assert len(prs) == 2
        assert prs[0].state == "merged"
        assert prs[1].task_id == str(task.id)
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
