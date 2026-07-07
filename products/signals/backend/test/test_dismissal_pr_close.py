from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.signals.backend.implementation_pr import PrCloseReason, close_implementation_pr_for_report
from products.signals.backend.models import SignalReport
from products.signals.backend.tasks import close_dismissed_report_pr

_PR_URL = "https://github.com/PostHog/posthog/pull/123"


class TestClosePrWhenReportDismissed(BaseTest):
    """The post_save receiver is the single choke point that closes a report's PR on archive."""

    def _create_report(self, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _save_transition(self, report: SignalReport, new_status: SignalReport.Status, **kwargs) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            updated = report.transition_to(new_status, **kwargs)
            report.save(update_fields=updated)

    @parameterized.expand(
        [
            ("suppressed", SignalReport.Status.READY, SignalReport.Status.SUPPRESSED, {}, "suppressed"),
            (
                "snooze_from_ready",
                SignalReport.Status.READY,
                SignalReport.Status.POTENTIAL,
                {"snooze_for": 5},
                "snoozed",
            ),
            ("snooze_from_resolved", SignalReport.Status.RESOLVED, SignalReport.Status.POTENTIAL, {}, "snoozed"),
        ]
    )
    def test_archive_transition_enqueues_close_task(
        self, _name, source_status, new_status, transition_kwargs, expected_reason
    ):
        report = self._create_report(report_status=source_status)
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            self._save_transition(report, new_status, **transition_kwargs)
        mock_task.delay.assert_called_once_with(
            report_id=str(report.id),
            team_id=self.team.id,
            reason=expected_reason,
        )

    def test_full_save_on_dismiss_enqueues_close_task(self):
        report = self._create_report()
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                report.transition_to(SignalReport.Status.SUPPRESSED)
                report.save()
        mock_task.delay.assert_called_once_with(
            report_id=str(report.id),
            team_id=self.team.id,
            reason="suppressed",
        )

    def test_full_save_without_status_change_does_not_enqueue(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                report.title = "edited"
                report.save()
        mock_task.delay.assert_not_called()

    def test_born_suppressed_report_does_not_enqueue(self):
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        mock_task.delay.assert_not_called()

    def test_restore_from_suppressed_does_not_enqueue(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            self._save_transition(report, SignalReport.Status.POTENTIAL)
        mock_task.delay.assert_not_called()

    def test_pipeline_reset_to_potential_does_not_enqueue(self):
        report = self._create_report(report_status=SignalReport.Status.IN_PROGRESS)
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            self._save_transition(report, SignalReport.Status.POTENTIAL, error="not actionable")
        mock_task.delay.assert_not_called()

    def test_unrelated_save_of_suppressed_report_does_not_enqueue(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                report.title = "edited"
                report.save(update_fields=["title"])
        mock_task.delay.assert_not_called()


class TestCloseDismissedReportPrTask(BaseTest):
    def test_task_invokes_close_helper_with_team_report_and_reason(self):
        with patch("products.signals.backend.tasks.close_implementation_pr_for_report") as mock_close:
            close_dismissed_report_pr(report_id="report-1", team_id=self.team.id, reason="snoozed")
        mock_close.assert_called_once_with(self.team.id, "report-1", reason="snoozed")


class TestCloseImplementationPrForReport(BaseTest):
    @parameterized.expand(
        [
            ("suppressed", "suppressed"),
            ("snoozed", "snoozed"),
        ]
    )
    def test_comments_on_and_closes_linked_pr(self, _name: str, reason: PrCloseReason):
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
            assert close_implementation_pr_for_report(self.team.id, "report-1", reason=reason) is True
        mock_resolve.assert_called_once_with(self.team.id, "PostHog/posthog")
        comment_body = github.comment_on_pull_request.call_args.args[2]
        assert reason in comment_body
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
