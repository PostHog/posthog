from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.signals.backend.implementation_pr import close_implementation_pr_for_report
from products.signals.backend.models import SignalReport
from products.signals.backend.tasks import close_dismissed_report_pr

_PR_URL = "https://github.com/PostHog/posthog/pull/123"


class TestClosePrWhenReportDismissed(BaseTest):
    """The post_save receiver is the single choke point that closes a report's PR on dismissal."""

    def _create_report(self, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def test_transition_into_suppressed_enqueues_close_task(self):
        report = self._create_report()
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(SignalReport.Status.SUPPRESSED)
                report.save(update_fields=updated)
        mock_task.delay.assert_called_once_with(report_id=str(report.id), team_id=self.team.id)

    def test_born_suppressed_report_does_not_enqueue(self):
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        mock_task.delay.assert_not_called()

    def test_restore_from_suppressed_does_not_enqueue(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                updated = report.transition_to(SignalReport.Status.POTENTIAL)
                report.save(update_fields=updated)
        mock_task.delay.assert_not_called()

    def test_unrelated_save_of_suppressed_report_does_not_enqueue(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                report.title = "edited"
                report.save(update_fields=["title"])
        mock_task.delay.assert_not_called()


class TestCloseDismissedReportPrTask(BaseTest):
    def test_task_invokes_close_helper_with_team_and_report(self):
        with patch("products.signals.backend.tasks.close_implementation_pr_for_report") as mock_close:
            close_dismissed_report_pr(report_id="report-1", team_id=self.team.id)
        mock_close.assert_called_once_with(self.team.id, "report-1")


class TestCloseImplementationPrForReport(BaseTest):
    def test_comments_on_and_closes_linked_pr(self):
        github = MagicMock()
        github.comment_on_pull_request.return_value = {"success": True}
        github.close_pull_request.return_value = {"success": True, "number": 123, "state": "closed"}
        with (
            patch(
                "products.signals.backend.implementation_pr.fetch_implementation_pr_urls_for_reports",
                return_value={"report-1": _PR_URL},
            ),
            patch(
                "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
                return_value=github,
            ) as mock_resolve,
        ):
            assert close_implementation_pr_for_report(self.team.id, "report-1") is True
        mock_resolve.assert_called_once_with(self.team.id, "PostHog/posthog")
        # An explanatory comment is left (on the parsed repo/PR number) before the PR is closed.
        assert github.comment_on_pull_request.call_args.args[:2] == ("PostHog/posthog", 123)
        github.close_pull_request.assert_called_once_with("PostHog/posthog", 123)

    def test_returns_false_and_skips_github_without_linked_pr(self):
        with (
            patch(
                "products.signals.backend.implementation_pr.fetch_implementation_pr_urls_for_reports",
                return_value={},
            ),
            patch(
                "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository"
            ) as mock_resolve,
        ):
            assert close_implementation_pr_for_report(self.team.id, "report-1") is False
        mock_resolve.assert_not_called()

    def test_returns_false_when_no_integration_resolves(self):
        with (
            patch(
                "products.signals.backend.implementation_pr.fetch_implementation_pr_urls_for_reports",
                return_value={"report-1": _PR_URL},
            ),
            patch(
                "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
                return_value=None,
            ),
        ):
            assert close_implementation_pr_for_report(self.team.id, "report-1") is False
