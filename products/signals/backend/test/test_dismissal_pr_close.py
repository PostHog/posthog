import uuid

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.team.team import Team

from products.signals.backend.implementation_pr import PrCloseReason, close_implementation_pr_for_report
from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportAssignment
from products.signals.backend.report_assignments import update_assignments_for_pull_request
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

    def test_resolve_outside_the_state_api_does_not_enqueue(self):
        # The PR-merge webhook resolves through transition_to directly. Its PR is merged, so the
        # receiver must not try to close it.
        report = self._create_report()
        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            self._save_transition(report, SignalReport.Status.RESOLVED)
        mock_task.delay.assert_not_called()

    def test_pr_closed_webhook_does_not_enqueue_for_any_linked_report(self):
        reports = [self._create_report(), self._create_report()]
        for report in reports:
            SignalReportAssignment.all_teams.create(
                team=self.team,
                report=report,
                pr_url=_PR_URL,
                repository="posthog/posthog",
                pr_number=123,
                pr_state=SignalReportAssignment.PrState.OPEN,
            )

        with patch("products.signals.backend.receivers.close_dismissed_report_pr") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                update_assignments_for_pull_request(
                    team_ids=[self.team.id],
                    repository="posthog/posthog",
                    pr_number=123,
                    pr_state=SignalReportAssignment.PrState.CLOSED,
                )

        mock_task.delay.assert_not_called()
        for report in reports:
            report.refresh_from_db()
            assert report.status == SignalReport.Status.SUPPRESSED

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
    def setUp(self):
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Test report",
            summary="Test summary",
        )
        self.assignment = SignalReportAssignment.all_teams.create(
            team=self.team,
            report=self.report,
            actor_kind=SignalActorKind.SYSTEM,
            pr_url=_PR_URL,
            repository="posthog/posthog",
            pr_number=123,
            pr_state=SignalReportAssignment.PrState.OPEN,
        )

    @parameterized.expand(
        [
            ("unclaimed", None),
            ("user", SignalActorKind.USER),
            ("agent", SignalActorKind.AGENT),
        ]
    )
    def test_does_not_touch_pr_without_trusted_claim_actor(self, _name: str, actor_kind: str | None):
        self.assignment.actor_kind = actor_kind
        self.assignment.save(update_fields=["actor_kind", "updated_at"])

        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository"
        ) as mock_resolve:
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is False

        mock_resolve.assert_not_called()

    def test_task_claim_actor_can_close_pr(self):
        self.assignment.actor_kind = SignalActorKind.TASK
        self.assignment.actor_task_id = uuid.uuid4()
        self.assignment.save(update_fields=["actor_kind", "actor_task_id", "updated_at"])
        github = MagicMock()
        github.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        github.comment_on_pull_request.return_value = {"success": True}
        github.close_pull_request.return_value = {"success": True}

        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is True

    @parameterized.expand(
        [
            ("suppressed", "suppressed"),
            ("snoozed", "snoozed"),
            ("resolved", "resolved"),
        ]
    )
    def test_comments_on_and_closes_linked_pr(self, _name: str, reason: PrCloseReason):
        github = MagicMock()
        github.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        github.comment_on_pull_request.return_value = {"success": True}
        github.close_pull_request.return_value = {"success": True, "number": 123, "state": "closed"}
        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ) as mock_resolve:
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id), reason=reason) is True

        mock_resolve.assert_called_once_with(self.team.id, "PostHog/posthog")
        comment_body = github.comment_on_pull_request.call_args.args[2]
        assert reason in comment_body
        github.close_pull_request.assert_called_once_with("PostHog/posthog", 123)
        self.assignment.refresh_from_db()
        assert self.assignment.pr_state == SignalReportAssignment.PrState.CLOSED
        assert self.assignment.pr_merged is False

    def test_returns_false_and_skips_github_without_linked_pr(self):
        self.assignment.pr_url = None
        self.assignment.repository = None
        self.assignment.pr_number = None
        self.assignment.pr_state = None
        self.assignment.save(update_fields=["pr_url", "repository", "pr_number", "pr_state", "updated_at"])

        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository"
        ) as mock_resolve:
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is False

        mock_resolve.assert_not_called()

    def test_returns_false_when_no_integration_resolves(self):
        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=None,
        ):
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is False

        self.assignment.refresh_from_db()
        assert self.assignment.pr_state == SignalReportAssignment.PrState.OPEN

    def test_does_not_close_a_report_pr_from_another_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository"
        ) as mock_resolve:
            assert close_implementation_pr_for_report(other_team.id, str(self.report.id)) is False

        mock_resolve.assert_not_called()
        self.assignment.refresh_from_db()
        assert self.assignment.pr_state == SignalReportAssignment.PrState.OPEN

    def _other_report_sharing_the_pr(self, report_status: str) -> SignalReport:
        other_report = SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Other report",
            summary="Other summary",
        )
        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=other_report,
            pr_url=_PR_URL,
            repository="posthog/posthog",
            pr_number=123,
            pr_state=SignalReportAssignment.PrState.OPEN,
        )
        return other_report

    def test_does_not_close_a_pr_another_live_report_still_uses(self):
        self._other_report_sharing_the_pr(SignalReport.Status.READY)

        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository"
        ) as mock_resolve:
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is False

        mock_resolve.assert_not_called()
        self.assignment.refresh_from_db()
        assert self.assignment.pr_state == SignalReportAssignment.PrState.OPEN

    @parameterized.expand(
        [
            ("suppressed", SignalReport.Status.SUPPRESSED),
            ("resolved", SignalReport.Status.RESOLVED),
        ]
    )
    def test_closes_the_pr_once_every_other_linked_report_is_finished(self, _name: str, other_status: str):
        self._other_report_sharing_the_pr(other_status)
        github = MagicMock()
        github.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        github.comment_on_pull_request.return_value = {"success": True}
        github.close_pull_request.return_value = {"success": True, "number": 123, "state": "closed"}

        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is True

        github.close_pull_request.assert_called_once_with("PostHog/posthog", 123)

    def test_keeps_a_merge_that_lands_during_the_github_round_trip(self):
        # Closing a merged PR reports success without reopening it, so a merge that arrives after the
        # status fetch would otherwise be overwritten with closed, permanently.
        def merge_lands(*args, **kwargs):
            SignalReportAssignment.all_teams.filter(pk=self.assignment.pk).update(
                pr_state=SignalReportAssignment.PrState.MERGED,
                pr_merged=True,
            )
            return {"success": True, "number": 123, "state": "closed"}

        github = MagicMock()
        github.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        github.comment_on_pull_request.return_value = {"success": True}
        github.close_pull_request.side_effect = merge_lands
        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            close_implementation_pr_for_report(self.team.id, str(self.report.id))

        self.assignment.refresh_from_db()
        assert self.assignment.pr_state == SignalReportAssignment.PrState.MERGED
        assert self.assignment.pr_merged is True

    def test_does_not_write_the_result_onto_a_replacement_pr(self):
        replacement_url = "https://github.com/PostHog/posthog/pull/456"

        def reclaim_swaps_the_pr(*args, **kwargs):
            SignalReportAssignment.all_teams.filter(pk=self.assignment.pk).update(
                pr_url=replacement_url,
                pr_number=456,
                pr_state=SignalReportAssignment.PrState.OPEN,
            )
            return {"success": True, "number": 123, "state": "closed"}

        github = MagicMock()
        github.get_pull_request.return_value = {"success": True, "state": "open", "merged": False}
        github.comment_on_pull_request.return_value = {"success": True}
        github.close_pull_request.side_effect = reclaim_swaps_the_pr
        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            close_implementation_pr_for_report(self.team.id, str(self.report.id))

        self.assignment.refresh_from_db()
        assert self.assignment.pr_url == replacement_url
        assert self.assignment.pr_state == SignalReportAssignment.PrState.OPEN

    @parameterized.expand(
        [
            (
                "already_closed",
                {"success": True, "state": "closed", "merged": False},
                SignalReportAssignment.PrState.CLOSED,
                False,
            ),
            (
                "already_merged",
                {"success": True, "state": "closed", "merged": True},
                SignalReportAssignment.PrState.MERGED,
                True,
            ),
        ]
    )
    def test_skips_comment_and_close_when_pr_not_open(
        self, _name: str, pr_status: dict, expected_state: str, expected_merged: bool
    ):
        github = MagicMock()
        github.get_pull_request.return_value = pr_status
        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is False

        github.comment_on_pull_request.assert_not_called()
        github.close_pull_request.assert_not_called()
        self.assignment.refresh_from_db()
        assert self.assignment.pr_state == expected_state
        assert self.assignment.pr_merged is expected_merged

    def test_skips_comment_and_close_when_status_unavailable(self):
        github = MagicMock()
        github.get_pull_request.return_value = {"success": False, "error": "boom", "status_code": 404}
        with patch(
            "products.signals.backend.implementation_pr.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert close_implementation_pr_for_report(self.team.id, str(self.report.id)) is False

        github.comment_on_pull_request.assert_not_called()
        github.close_pull_request.assert_not_called()
        self.assignment.refresh_from_db()
        assert self.assignment.pr_state == SignalReportAssignment.PrState.OPEN
