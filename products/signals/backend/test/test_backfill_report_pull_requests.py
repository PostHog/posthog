from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.signals.backend.models import (
    SignalPullRequest,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
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
        claim_id = assignment.claim_id
        assert claim_id is not None
        assert assignment.actor_user_id == self.user.id
        assert SignalReportAssignment.all_teams.filter(report=task_report).count() == 0
        assert SignalPullRequest.objects.for_team(self.team.id).count() == 2
        assert (
            SignalReportArtefact.objects.filter(report=task_report, type="pull_request", actor_kind="task").count() == 2
        )
        assert SignalReportArtefact.objects.get(report=released, type="pull_request").actor_kind is None
        imported = SignalReportArtefact.objects.get(report=deleted_principal, type="pull_request")
        assert imported.actor_kind == "agent"
        assert imported.actor_agent == "example-agent"
        assert not SignalPullRequest.objects.for_team(self.team.id).filter(checked_at__isnull=False).exists()
        update_assignments_for_pull_request(
            team_ids=[self.team.id], repository="example/app", pr_number=1, pr_state="merged"
        )
        count = SignalReportArtefact.objects.filter(team=self.team).count()
        call_command(
            "backfill_report_pull_requests", team_id=self.team.id, batch_size=1, after=str(active.id), stdout=StringIO()
        )
        call_command("backfill_report_pull_requests", team_id=self.team.id, batch_size=1, stdout=StringIO())
        assert SignalReportArtefact.objects.filter(team=self.team).count() == count
        assert SignalPullRequest.objects.for_team(self.team.id).get(number=1).state == "merged"
        assignment.refresh_from_db()
        assert assignment.claim_id == claim_id
        task_report.refresh_from_db()
        assert task_report.status == "ready"
