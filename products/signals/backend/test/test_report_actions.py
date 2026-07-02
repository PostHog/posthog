from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.signals.backend.implementation_pr import close_implementation_pr_for_report
from products.signals.backend.models import SignalReport
from products.signals.backend.report_actions import suppress_report_from_slack

_PR_URL = "https://github.com/PostHog/posthog/pull/123"


class TestSuppressReportFromSlack(BaseTest):
    def _create_report(self, report_status=SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def test_dismiss_comments_on_and_closes_linked_implementation_pr(self):
        report = self._create_report()
        github = MagicMock()
        github.comment_on_pull_request_from_url.return_value = {"success": True}
        github.close_pull_request_from_url.return_value = {"success": True, "number": 123, "state": "closed"}

        with (
            patch(
                "products.signals.backend.implementation_pr.fetch_implementation_pr_urls_for_reports",
                return_value={str(report.id): _PR_URL},
            ),
            patch(
                "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
                return_value=github,
            ) as mock_resolve,
        ):
            assert suppress_report_from_slack(self.team.id, str(report.id), slack_user_id="U1") is True

        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED
        mock_resolve.assert_called_once_with(self.team.id, "PostHog/posthog")
        # An explanatory comment is left before the PR is closed.
        assert github.comment_on_pull_request_from_url.call_args.args[0] == _PR_URL
        github.close_pull_request_from_url.assert_called_once_with(_PR_URL)

    def test_dismiss_already_suppressed_does_not_close_again(self):
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        with patch("products.signals.backend.implementation_pr.fetch_implementation_pr_urls_for_reports") as mock_fetch:
            assert suppress_report_from_slack(self.team.id, str(report.id)) is True
        mock_fetch.assert_not_called()

    def test_dismiss_succeeds_when_pr_close_fails(self):
        # A GitHub failure must never undo the dismiss — suppression already committed.
        report = self._create_report()
        with (
            patch(
                "products.signals.backend.implementation_pr.fetch_implementation_pr_urls_for_reports",
                return_value={str(report.id): _PR_URL},
            ),
            patch(
                "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
                side_effect=Exception("github down"),
            ),
        ):
            assert suppress_report_from_slack(self.team.id, str(report.id)) is True
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED


class TestCloseImplementationPrForReport(BaseTest):
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
            assert close_implementation_pr_for_report(self.team.id, "some-report-id") is False
        mock_resolve.assert_not_called()

    def test_returns_false_when_no_integration_resolves(self):
        with (
            patch(
                "products.signals.backend.implementation_pr.fetch_implementation_pr_urls_for_reports",
                return_value={"some-report-id": _PR_URL},
            ),
            patch(
                "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
                return_value=None,
            ),
        ):
            assert close_implementation_pr_for_report(self.team.id, "some-report-id") is False
