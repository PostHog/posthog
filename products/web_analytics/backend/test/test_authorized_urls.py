from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.health_issue import HealthIssue
from posthog.tasks.health_checks import evaluate_health_check_for_team

from products.web_analytics.backend.temporal.health_checks.authorized_urls import AuthorizedUrlsCheck


class TestAuthorizedUrlsEvaluation(BaseTest):
    def test_creates_issue_when_team_has_no_app_urls(self):
        self.team.app_urls = []
        self.team.save()
        HealthIssue.objects.filter(team_id=self.team.id, kind=AuthorizedUrlsCheck.kind).delete()

        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)

        issues = HealthIssue.objects.filter(
            team_id=self.team.id,
            kind=AuthorizedUrlsCheck.kind,
            status=HealthIssue.Status.ACTIVE,
        )
        self.assertEqual(issues.count(), 1)
        self.assertEqual(issues.get().severity, HealthIssue.Severity.WARNING)

    def test_resolves_active_issue_when_team_has_app_urls(self):
        self.team.app_urls = []
        self.team.save()
        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)
        self.assertEqual(
            HealthIssue.objects.filter(
                team_id=self.team.id, kind=AuthorizedUrlsCheck.kind, status=HealthIssue.Status.ACTIVE
            ).count(),
            1,
        )

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)

        self.assertEqual(
            HealthIssue.objects.filter(
                team_id=self.team.id, kind=AuthorizedUrlsCheck.kind, status=HealthIssue.Status.ACTIVE
            ).count(),
            0,
        )
        self.assertEqual(
            HealthIssue.objects.filter(
                team_id=self.team.id, kind=AuthorizedUrlsCheck.kind, status=HealthIssue.Status.RESOLVED
            ).count(),
            1,
        )

    def test_idempotent_for_healthy_team(self):
        self.team.app_urls = ["https://example.com"]
        self.team.save()

        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)
        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)

        self.assertEqual(
            HealthIssue.objects.filter(team_id=self.team.id, kind=AuthorizedUrlsCheck.kind).count(),
            0,
        )


class TestAuthorizedUrlsSignal(BaseTest):
    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_team_save_dispatches_task_on_commit(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.app_urls = ["https://example.com"]
            self.team.save()

        mock_task.delay.assert_called_with("authorized_urls", self.team.id)

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_task_not_dispatched_before_commit(self, mock_task):
        with self.captureOnCommitCallbacks(execute=False):
            self.team.app_urls = ["https://example.com"]
            self.team.save()

        mock_task.delay.assert_not_called()

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_task_not_dispatched_when_app_urls_not_in_update_fields(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.name = "renamed"
            self.team.save(update_fields=["name"])

        mock_task.delay.assert_not_called()

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_task_dispatched_when_app_urls_in_update_fields(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.app_urls = ["https://example.com"]
            self.team.save(update_fields=["app_urls"])

        mock_task.delay.assert_called_with("authorized_urls", self.team.id)
