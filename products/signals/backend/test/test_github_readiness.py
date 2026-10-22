from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus, github_readiness
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration

from products.signals.backend.github_readiness import (
    LEGACY_GITHUB_BLOCKERS,
    check_report_github_readiness,
    enabled_recovery_signals,
)
from products.signals.backend.github_readiness_tasks import resume_github_blocked_reports
from products.signals.backend.models import SignalReport, SignalSourceConfig
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.facade.repo_selection import get_team_github_readiness, resolve_team_github_integration

MODULE = "products.signals.backend.github_readiness"
TASKS = "products.signals.backend.github_readiness_tasks"


@time_machine.travel("2026-01-15T12:00:00Z", tick=False)
class TestGitHubReadiness(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="123",
            config={"installation_id": "123"},
            repository_cache=[{"full_name": "example/application"}],
            repository_cache_updated_at=timezone.now(),
        )
        self.github = GitHubIntegration(self.integration, source="test", priority=Priority.NORMAL)

    @parameterized.expand(
        [
            ("not_connected",),
            ("reconnect_required",),
            ("no_repositories",),
            ("temporarily_unavailable",),
        ]
    )
    def test_blocking_keeps_report_unpublished(self, reason: str) -> None:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.CANDIDATE)
        with patch(
            f"{MODULE}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus(reason))
        ):
            self.assertFalse(check_report_github_readiness(self.team.id, str(report.id)))
        report.refresh_from_db()
        self.assertEqual(report.status, SignalReport.Status.CANDIDATE)
        self.assertEqual(report.research_blocked_reason, reason)
        self.assertIsNone(report.first_visible_at)
        self.assertEqual(report.run_count, 0)

    def test_access_lost_during_selection_returns_report_to_queue(self) -> None:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.IN_PROGRESS, run_count=1)
        with patch(f"{MODULE}.get_team_github_readiness") as resolve:
            self.assertFalse(check_report_github_readiness(self.team.id, str(report.id), "temporarily_unavailable"))
        resolve.assert_not_called()
        report.refresh_from_db()
        self.assertEqual(report.status, SignalReport.Status.CANDIDATE)
        self.assertEqual(report.research_blocked_reason, "temporarily_unavailable")
        self.assertIsNone(report.first_visible_at)
        self.assertEqual(report.run_count, 1)

    def test_readiness_does_not_reopen_dismissed_report(self) -> None:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.SUPPRESSED)
        with patch(f"{MODULE}.get_team_github_readiness") as resolve:
            self.assertFalse(check_report_github_readiness(self.team.id, str(report.id)))
        resolve.assert_not_called()

    def test_stale_empty_snapshot_can_be_revalidated(self) -> None:
        self.integration.repository_cache = []
        self.integration.repository_cache_updated_at = timezone.now() - timedelta(hours=2)
        self.integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
        self.assertIsNotNone(resolve_team_github_integration(self.team.id))
        self.assertEqual(github_readiness(self.github).status, GitHubReadinessStatus.TEMPORARILY_UNAVAILABLE)
        with patch.object(
            GitHubIntegration, "sync_repository_cache", return_value=[{"full_name": "example/application"}]
        ):
            self.assertEqual(get_team_github_readiness(self.team.id, verify=True).status, GitHubReadinessStatus.READY)

    def test_transient_refresh_error_is_retried_without_reconnection(self) -> None:
        self.integration.errors = "TOKEN_REFRESH_FAILED"
        with (
            patch.object(self.github, "refresh_access_token") as refresh,
            patch.object(self.github, "sync_repository_cache", return_value=[{}]),
        ):
            self.assertEqual(github_readiness(self.github, verify=True).status, GitHubReadinessStatus.READY)
        refresh.assert_called_once()

    def test_background_readiness_only_uses_an_owners_personal_connection(self) -> None:
        self.integration.delete()
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save(update_fields=["level"])
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="456",
            config={"installation_id": "456"},
            repository_cache=[{"full_name": "example/application"}],
            repository_cache_updated_at=timezone.now(),
        )
        self.assertEqual(get_team_github_readiness(self.team.id).status, GitHubReadinessStatus.NOT_CONNECTED)
        membership.level = OrganizationMembership.Level.OWNER
        membership.save(update_fields=["level"])
        self.assertEqual(get_team_github_readiness(self.team.id).status, GitHubReadinessStatus.READY)

    def test_unavailable_installation_does_not_retry_on_each_report(self) -> None:
        self.integration.config["installation_unavailable_since"] = 1
        with patch.object(self.github, "refresh_access_token") as refresh:
            self.assertEqual(
                github_readiness(self.github, verify=True).status, GitHubReadinessStatus.RECONNECT_REQUIRED
            )
        refresh.assert_not_called()

    @parameterized.expand([(True, False), (False, True)])
    def test_recovery_respects_quota_and_daily_limit(self, quota: bool, daily: bool) -> None:
        SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.CANDIDATE, research_blocked_reason="not_connected"
        )
        with (
            patch(f"{TASKS}.self_driving_quota_gate", return_value=Mock(enforced=quota)),
            patch(f"{TASKS}.daily_report_limit_gate", return_value=Mock(limited=daily)),
            patch(f"{TASKS}.get_team_github_readiness") as resolve,
        ):
            resume_github_blocked_reports(self.team.id)
        resolve.assert_not_called()

    def test_recovery_only_restarts_github_blocked_reports(self) -> None:
        queued = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.CANDIDATE, research_blocked_reason="not_connected"
        )
        legacy = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.PENDING_INPUT, error=LEGACY_GITHUB_BLOCKERS[0]
        )
        dismissed = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.SUPPRESSED, research_blocked_reason="not_connected"
        )
        human = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.PENDING_INPUT, error="Requires a product decision"
        )
        with (
            patch(f"{TASKS}.self_driving_quota_gate", return_value=Mock(enforced=False)),
            patch(f"{TASKS}.daily_report_limit_gate", return_value=Mock(limited=False)),
            patch(
                f"{TASKS}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus.READY)
            ),
            patch(f"{TASKS}.start_recovered_report", new_callable=AsyncMock) as start,
        ):
            resume_github_blocked_reports(self.team.id)
        self.assertEqual({call.args[1] for call in start.await_args_list}, {str(queued.id), str(legacy.id)})
        dismissed.refresh_from_db()
        human.refresh_from_db()
        self.assertEqual(dismissed.status, SignalReport.Status.SUPPRESSED)
        self.assertEqual(human.status, SignalReport.Status.PENDING_INPUT)

    def test_recovery_filters_disabled_sources(self) -> None:
        enabled = SignalData(
            signal_id=str(uuid4()),
            source_product="error_tracking",
            source_type="issue_created",
            source_id="example-issue",
            content="A synthetic exception",
            weight=1,
            timestamp=timezone.now(),
        )
        disabled = SignalData(
            signal_id=str(uuid4()),
            source_product="linear",
            source_type="issue",
            source_id="example-ticket",
            content="A synthetic request",
            weight=1,
            timestamp=timezone.now(),
        )
        SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
        )
        SignalSourceConfig.objects.create(team=self.team, source_product="linear", source_type="issue", enabled=False)
        self.assertEqual(enabled_recovery_signals(self.team.id, [enabled, disabled]), [enabled])
