from collections.abc import Callable

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.tasks.health_checks import evaluate_health_check_for_team

from products.event_definitions.backend.models import EventDefinition
from products.web_analytics.backend.temporal.health_checks.authorized_urls import AuthorizedUrlsCheck


def _set_app_urls(team: Team) -> None:
    team.app_urls = ["https://example.com"]
    team.save()


def _become_server_only(team: Team) -> None:
    team.ingested_event = True
    team.save()
    EventDefinition.objects.create(
        team=team, project_id=team.project_id, name="$mcp_tool_call", last_seen_at=timezone.now()
    )


class TestAuthorizedUrlsEvaluation(BaseTest):
    @parameterized.expand(
        [
            ("nothing_ingested_yet", False, None, 1),
            ("web_project", True, "$pageview", 1),
            ("server_only_project", True, "$mcp_tool_call", 0),
        ]
    )
    def test_issue_when_team_has_no_app_urls(
        self, _name: str, ingested_event: bool, seen_event: str | None, expected_issues: int
    ):
        self.team.app_urls = []
        self.team.ingested_event = ingested_event
        self.team.save()
        if seen_event:
            EventDefinition.objects.create(
                team=self.team, project_id=self.team.project_id, name=seen_event, last_seen_at=timezone.now()
            )
        HealthIssue.objects.filter(team_id=self.team.id, kind=AuthorizedUrlsCheck.kind).delete()

        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)

        issues = HealthIssue.objects.filter(
            team_id=self.team.id,
            kind=AuthorizedUrlsCheck.kind,
            status=HealthIssue.Status.ACTIVE,
        )
        self.assertEqual(issues.count(), expected_issues)
        if expected_issues:
            self.assertEqual(issues.get().severity, HealthIssue.Severity.WARNING)

    @parameterized.expand([("team_sets_app_urls", _set_app_urls), ("team_is_server_only", _become_server_only)])
    def test_resolves_active_issue(self, _name: str, make_healthy: Callable[[Team], None]):
        self.team.app_urls = []
        self.team.save()
        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)
        self.assertEqual(
            HealthIssue.objects.filter(
                team_id=self.team.id, kind=AuthorizedUrlsCheck.kind, status=HealthIssue.Status.ACTIVE
            ).count(),
            1,
        )

        make_healthy(self.team)
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
