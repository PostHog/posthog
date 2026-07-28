from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.signals.backend.implementation_pr import ImplementationPr, sync_reviewers_to_github_for_report
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.tasks import sync_report_reviewers_to_github

_PR_URL = "https://github.com/PostHog/posthog/pull/42"


class TestSyncReviewersReceiver(BaseTest):
    """The post_save receiver is the single choke point that syncs reviewers to the PR on change."""

    def _create_report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )

    @parameterized.expand(
        [
            (SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS, '[{"github_login": "octocat"}]', True),
            (SignalReportArtefact.ArtefactType.NOTE, '{"note": "hi"}', False),
        ]
    )
    def test_only_reviewers_artefact_enqueues_sync(self, artefact_type, content, should_enqueue):
        report = self._create_report()
        with patch("products.signals.backend.receivers.sync_report_reviewers_to_github") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                SignalReportArtefact.objects.create(team=self.team, report=report, type=artefact_type, content=content)
        if should_enqueue:
            mock_task.delay.assert_called_once_with(report_id=str(report.id), team_id=self.team.id)
        else:
            mock_task.delay.assert_not_called()

    def test_in_place_reviewers_edit_enqueues_sync(self):
        # update_content edits the latest row in place (created=False), so the receiver must not be
        # gated on `created` or a reviewer edit would silently never reach the PR.
        report = self._create_report()
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content='[{"github_login": "octocat"}]',
        )
        with patch("products.signals.backend.receivers.sync_report_reviewers_to_github") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                artefact.update_content([{"github_login": "hubber"}])
        mock_task.delay.assert_called_once_with(report_id=str(report.id), team_id=self.team.id)


class TestSyncReportReviewersTask(BaseTest):
    def test_task_forwards_team_and_report_in_the_right_order(self):
        # The task takes (report_id, team_id) but the helper takes (team_id, report_id); a swap here
        # would be a silent cross-argument bug, so pin the order.
        with patch("products.signals.backend.tasks.sync_reviewers_to_github_for_report") as mock_sync:
            sync_report_reviewers_to_github(report_id="report-1", team_id=self.team.id)
        mock_sync.assert_called_once_with(self.team.id, "report-1")


class TestSyncReviewersToGithubForReport(BaseTest):
    def _report_with_reviewers(self, logins: list[str]) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )
        content = "[" + ", ".join(f'{{"github_login": "{login}"}}' for login in logins) + "]"
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=content,
        )
        return report

    def _github_mock(self, *, already: list[str]) -> MagicMock:
        github = MagicMock()
        github.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        github.get_requested_reviewer_logins.return_value = {"success": True, "logins": already}
        github.request_pull_request_reviewers.return_value = {"success": True, "requested": [], "rejected": []}
        return github

    def _run(self, report: SignalReport, github: MagicMock | None, *, merged: bool = False) -> bool:
        with (
            patch(
                "products.signals.backend.implementation_pr.fetch_implementation_pr_state_for_reports",
                return_value={str(report.id): ImplementationPr(url=_PR_URL, merged=merged)},
            ),
            patch(
                "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
                return_value=github,
            ),
        ):
            return sync_reviewers_to_github_for_report(self.team.id, str(report.id))

    def test_requests_only_the_reviewers_the_pr_is_missing(self):
        report = self._report_with_reviewers(["octocat", "hubber"])
        github = self._github_mock(already=["octocat"])
        assert self._run(report, github) is True
        github.request_pull_request_reviewers.assert_called_once_with("PostHog/posthog", 42, ["hubber"])

    def test_noop_when_pr_already_has_every_reviewer(self):
        report = self._report_with_reviewers(["octocat"])
        github = self._github_mock(already=["octocat"])
        assert self._run(report, github) is True
        github.request_pull_request_reviewers.assert_not_called()

    def test_skips_merged_pr_without_touching_github(self):
        report = self._report_with_reviewers(["octocat"])
        github = self._github_mock(already=[])
        assert self._run(report, github, merged=True) is False
        github.get_pull_request.assert_not_called()

    def test_skips_closed_but_unmerged_pr(self):
        report = self._report_with_reviewers(["octocat"])
        github = self._github_mock(already=[])
        github.get_pull_request.return_value = {"success": True, "state": "closed", "merged": False}
        assert self._run(report, github) is False
        github.request_pull_request_reviewers.assert_not_called()

    def test_returns_false_when_report_has_no_known_reviewers(self):
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )
        github = self._github_mock(already=[])
        assert self._run(report, github) is False
        github.get_pull_request.assert_not_called()
