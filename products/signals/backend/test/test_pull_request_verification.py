from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority

from products.signals.backend.management.commands.reconcile_report_pull_requests import reconcile_report_pull_requests
from products.signals.backend.models import SignalReport, SignalReportPullRequest
from products.signals.backend.pull_requests import verify_pull_request_state
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.models import Task, TaskRun

_PR_URL = "https://github.com/PostHog/posthog/pull/42"


class TestPullRequestVerification(BaseTest):
    def _report(self, status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=status, title="Test report", summary="Test summary")

    def _task(self) -> Task:
        return Task.objects.create(team=self.team, title="Implementation", description="", origin_product="signals")

    def _task_run(self, report: SignalReport, output: dict, task: Task | None = None) -> MagicMock:
        """Attach a pull request the way a task run does, leaving the queued GitHub read unrun."""
        task = task or self._task()
        record_implementation_task(team_id=self.team.id, report_id=str(report.id), task_id=str(task.id))
        with patch("products.signals.backend.tasks.verify_implementation_pr_state.delay") as verify:
            with self.captureOnCommitCallbacks(execute=True):
                TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.COMPLETED, output=output)
        return verify

    def _merged_task_run(self, report: SignalReport) -> MagicMock:
        return self._task_run(report, {"pr_url": _PR_URL, "pr_state": "merged", "pr_merged": True})

    def test_task_reported_merge_holds_the_report_open_and_queues_a_github_read(self):
        report = self._report()
        verify = self._merged_task_run(report)
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        verify.assert_called_with(team_id=self.team.id, pr_url=_PR_URL)

    @parameterized.expand(
        [
            ("merged", {"success": True, "state": "closed", "merged": True}, "merged", SignalReport.Status.RESOLVED),
            ("open", {"success": True, "state": "open", "merged": False}, "open", SignalReport.Status.READY),
            (
                "closed_unmerged",
                {"success": True, "state": "closed", "merged": False},
                "closed",
                SignalReport.Status.SUPPRESSED,
            ),
        ]
    )
    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_github_decides_the_report_state(self, _name, status, expected_pr_state, expected_status, integration):
        integration.return_value.get_pull_request.return_value = status
        report = self._report()
        self._merged_task_run(report)

        verify_pull_request_state(team_id=self.team.id, pr_url=_PR_URL)

        pr = SignalReportPullRequest.objects.for_team(self.team.id).get(repository="posthog/posthog", number=42)
        assert pr.state == expected_pr_state
        assert pr.checked_at is not None
        report.refresh_from_db()
        assert report.status == expected_status

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_report_resolved_on_a_merge_that_never_happened_is_reopened(self, integration):
        integration.return_value.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        report = self._report()
        self._merged_task_run(report)
        # The state this fix prevents: the report was resolved while GitHub still has the PR open.
        report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))

        verify_pull_request_state(team_id=self.team.id, pr_url=_PR_URL)

        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_a_confirmed_merge_survives_a_later_unverified_state(self, integration):
        integration.return_value.get_pull_request.return_value = {"success": True, "state": "closed", "merged": True}
        report = self._report()
        self._merged_task_run(report)
        verify_pull_request_state(team_id=self.team.id, pr_url=_PR_URL)

        self._task_run(report, {"pr_url": _PR_URL, "pr_state": "open", "pr_merged": False}, task=Task.objects.get())

        assert (
            SignalReportPullRequest.objects.for_team(self.team.id).get(repository="posthog/posthog", number=42).state
            == "merged"
        )
        report.refresh_from_db()
        assert report.status == SignalReport.Status.RESOLVED

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_a_failed_github_read_leaves_the_report_open(self, integration):
        integration.return_value.get_pull_request.return_value = {"success": False, "error": "not found"}
        report = self._report()
        self._merged_task_run(report)

        assert verify_pull_request_state(team_id=self.team.id, pr_url=_PR_URL) is None

        pr = SignalReportPullRequest.objects.for_team(self.team.id).get(repository="posthog/posthog", number=42)
        assert pr.checked_at is None
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_the_bulk_sweep_reads_github_on_the_sheddable_lane(self, integration):
        integration.return_value.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        self._merged_task_run(self._report())

        list(reconcile_report_pull_requests(team_id=self.team.id, after=None, batch_size=10))

        assert integration.call_args.kwargs == {"source": "signals_pr_reconcile", "priority": Priority.BATCH}
