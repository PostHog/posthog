from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase, GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.integration.github_readiness import GitHubReadiness, GitHubReadinessStatus, github_readiness
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration

from products.signals.backend.github_readiness import (
    LEGACY_GITHUB_BLOCKERS,
    check_implementation_github_readiness,
    check_report_github_readiness,
    enabled_recovery_signals,
)
from products.signals.backend.github_readiness_tasks import resume_github_blocked_reports
from products.signals.backend.models import SignalReport, SignalSourceConfig
from products.signals.backend.scout_harness.run_gates import check_github_gate
from products.signals.backend.scout_harness.runner import arun_signals_scout
from products.signals.backend.temporal.signal_queries import (
    FetchSignalsForReportInput,
    fetch_signals_for_report_activity,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.facade.repo_selection import get_team_github_readiness, resolve_team_github_integration

MODULE = "products.signals.backend.github_readiness"
TASKS = "products.signals.backend.github_readiness_tasks"
QUERIES = "products.signals.backend.temporal.signal_queries"


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
        self.assertEqual(report.research_blocked_at, timezone.now())
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

    @parameterized.expand(
        [
            ("not_connected", False, 1, False),
            ("reconnect_required", False, 1, False),
            ("no_repositories", False, 1, False),
            ("not_connected", True, 6, True),
            ("not_connected", True, 7, False),
            ("temporarily_unavailable", False, 6, True),
            ("temporarily_unavailable", True, 8, False),
        ]
    )
    def test_suspended_research_only_resumes_within_its_recovery_window(
        self, reason: str, recovery: bool, age_days: int, resumes: bool
    ) -> None:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason=reason,
            research_blocked_at=timezone.now() - timedelta(days=age_days),
        )
        with patch(
            f"{MODULE}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus.READY)
        ) as readiness:
            self.assertEqual(check_report_github_readiness(self.team.id, str(report.id), recovery=recovery), resumes)
        self.assertEqual(readiness.call_count, int(resumes))

    def test_repeated_selection_failures_do_not_extend_recovery_window(self) -> None:
        blocked_at = timezone.now() - timedelta(days=6)
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="temporarily_unavailable",
            research_blocked_at=blocked_at,
        )
        fields = report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=0)
        report.save(update_fields=fields)
        self.assertFalse(check_report_github_readiness(self.team.id, str(report.id), "temporarily_unavailable"))
        report.refresh_from_db()
        self.assertEqual(report.research_blocked_at, blocked_at)

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

    @parameterized.expand([("project", False), ("project", True), ("owner", True)])
    def test_selection_preserves_usable_connection_after_stale_refresh_fails(
        self, stale_source: str, usable_owner: bool
    ) -> None:
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        membership.level = OrganizationMembership.Level.OWNER
        membership.save(update_fields=["level"])
        self.integration.repository_cache = []
        self.integration.repository_cache_updated_at = timezone.now() - timedelta(hours=2)
        self.integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
        if stale_source == "owner":
            self.integration.delete()
            stale = UserIntegration.objects.create(
                user=self.user,
                kind="github",
                integration_id="stale",
                config={"installation_id": "stale"},
                repository_cache=[],
                repository_cache_updated_at=timezone.now() - timedelta(hours=2),
            )
            UserIntegration.objects.filter(pk=stale.pk).update(created_at=timezone.now() + timedelta(hours=1))
        repository = {"id": 1, "full_name": "example/application", "name": "application", "private": True}
        if usable_owner:
            usable: Integration | UserIntegration = UserIntegration.objects.create(
                user=self.user,
                kind="github",
                integration_id="usable",
                config={"installation_id": "usable"},
                repository_cache=[repository],
                repository_cache_updated_at=timezone.now(),
            )
        else:
            usable = Integration.objects.create(
                team=self.team,
                kind="github",
                integration_id="usable",
                config={"installation_id": "usable"},
                repository_cache=[repository],
                repository_cache_updated_at=timezone.now(),
            )

        def refresh(github: GitHubIntegrationBase, **kwargs: object) -> list[dict]:
            if github.integration.integration_id != "usable":
                raise GitHubIntegrationError("Repository refresh unavailable")
            return [repository]

        with patch.object(GitHubIntegrationBase, "sync_repository_cache", autospec=True, side_effect=refresh):
            readiness = get_team_github_readiness(self.team.id, verify=True)
        self.assertEqual(readiness.status, GitHubReadinessStatus.READY)
        selected = resolve_team_github_integration(self.team.id)
        assert selected is not None
        self.assertEqual(selected.integration, usable)
        self.assertEqual(
            [repo["full_name"] for repo in selected.list_all_cached_repositories(allow_refresh=False)],
            ["example/application"],
        )

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

    @parameterized.expand(
        [
            # A quota pause follows the next-matching-signal rule, so the sweep does not retry it.
            (True, False, None),
            # Other prerequisites keep the reconnect for the periodic sweep.
            (False, True, "temporarily_unavailable"),
        ]
    )
    def test_reconnect_recovery_stopped_by_a_prerequisite_keeps_its_intent(
        self, quota: bool, daily: bool, expected_reason: str | None
    ) -> None:
        blocked = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="not_connected",
            research_blocked_at=timezone.now() - timedelta(days=2),
        )
        legacy = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.PENDING_INPUT, error=LEGACY_GITHUB_BLOCKERS[0]
        )
        SignalReport.objects.filter(id=legacy.id).update(created_at=timezone.now() - timedelta(days=3))
        with (
            patch(f"{TASKS}.self_driving_quota_gate", return_value=Mock(enforced=quota)),
            patch(f"{TASKS}.daily_report_limit_gate", return_value=Mock(limited=daily)),
            patch(f"{TASKS}.get_team_github_readiness") as resolve,
            patch(f"{TASKS}.start_recovered_report", new_callable=AsyncMock) as start,
        ):
            resume_github_blocked_reports(self.team.id, connection_restored=True)
        resolve.assert_not_called()
        start.assert_not_awaited()
        blocked.refresh_from_db()
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, SignalReport.Status.CANDIDATE)
        self.assertEqual(
            [blocked.research_blocked_reason, legacy.research_blocked_reason], [expected_reason, expected_reason]
        )
        # The original recovery window still applies.
        self.assertEqual(blocked.research_blocked_at, timezone.now() - timedelta(days=2))
        self.assertEqual(legacy.research_blocked_at, timezone.now() - timedelta(days=3))

    @parameterized.expand([(False,), (True,)])
    def test_recovery_only_restarts_github_blocked_reports(self, connection_restored: bool) -> None:
        queued = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="not_connected",
            research_blocked_at=timezone.now(),
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
        transient = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="temporarily_unavailable",
            research_blocked_at=timezone.now(),
        )
        SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="temporarily_unavailable",
            research_blocked_at=timezone.now() - timedelta(days=8),
        )
        expired_legacy = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.PENDING_INPUT,
            error=LEGACY_GITHUB_BLOCKERS[0],
        )
        SignalReport.objects.filter(id=expired_legacy.id).update(created_at=timezone.now() - timedelta(days=8))
        with (
            patch(f"{TASKS}.self_driving_quota_gate", return_value=Mock(enforced=False)),
            patch(f"{TASKS}.daily_report_limit_gate", return_value=Mock(limited=False)),
            patch(
                f"{TASKS}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus.READY)
            ),
            patch(f"{TASKS}.start_recovered_report", new_callable=AsyncMock) as start,
        ):
            resume_github_blocked_reports(self.team.id, connection_restored=connection_restored)
        expected = {str(transient.id)}
        if connection_restored:
            expected.update((str(queued.id), str(legacy.id)))
        self.assertEqual({call.args[1] for call in start.await_args_list}, expected)
        dismissed.refresh_from_db()
        human.refresh_from_db()
        self.assertEqual(dismissed.status, SignalReport.Status.SUPPRESSED)
        self.assertEqual(human.status, SignalReport.Status.PENDING_INPUT)

    @parameterized.expand([(None, 2), ("temporarily_unavailable", 1)])
    def test_recovery_filters_disabled_sources(self, blocked_reason: str | None, fetched: int) -> None:
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
        # A new matching signal restarts a blocked report without the recovery input, so the
        # persisted blocker alone has to select the filter.
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.CANDIDATE, research_blocked_reason=blocked_reason
        )
        with (
            patch(
                f"{QUERIES}.execute_hogql_query_with_retry", AsyncMock(return_value=Mock(results=[enabled, disabled]))
            ),
            patch(f"{QUERIES}._parse_signal_row", side_effect=lambda row: row),
            # The test transaction is visible only on this thread.
            patch(f"{QUERIES}.database_sync_to_async", lambda fn, **_: sync_to_async(fn, thread_sensitive=True)),
        ):
            result = async_to_sync(fetch_signals_for_report_activity)(
                FetchSignalsForReportInput(team_id=self.team.id, report_id=str(report.id))
            )
        self.assertEqual(len(result.signals), fetched)
        self.assertEqual(result.fetched_signal_count, 2)

    def test_periodic_recovery_stops_when_the_connection_is_removed(self) -> None:
        self.integration.delete()
        blocked_at = timezone.now() - timedelta(days=1)
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="temporarily_unavailable",
            research_blocked_at=blocked_at,
        )
        with (
            patch(f"{TASKS}.self_driving_quota_gate", return_value=Mock(enforced=False)),
            patch(f"{TASKS}.daily_report_limit_gate", return_value=Mock(limited=False)),
        ):
            resume_github_blocked_reports(self.team.id)
        report.refresh_from_db()
        self.assertEqual(report.research_blocked_reason, "not_connected")
        self.assertEqual(report.research_blocked_at, blocked_at)
        with patch(f"{TASKS}.get_team_github_readiness") as readiness:
            resume_github_blocked_reports(self.team.id)
        readiness.assert_not_called()

    def test_scout_cannot_run_without_github_or_create_a_run_row(self) -> None:
        self.integration.delete()
        rejection = check_github_gate(self.team.id)
        assert rejection is not None
        self.assertEqual(rejection.reason, "github_not_connected")
        with (
            patch("products.signals.backend.scout_harness.runner._get_team", return_value=self.team),
            patch("products.signals.backend.scout_harness.runner.check_github_gate", return_value=rejection),
            patch("products.signals.backend.scout_harness.runner.sync_canonical_skills") as seed,
        ):
            result = async_to_sync(arun_signals_scout)(team_id=self.team.id, skill_name="signals-scout-example")
        self.assertIsNone(result.run_id)
        self.assertEqual(result.skip_reason, "github_not_connected")
        seed.assert_not_called()

    def test_implementation_blocker_clears_when_access_recovers(self) -> None:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        with patch(
            f"{MODULE}.get_team_github_readiness",
            return_value=GitHubReadiness(status=GitHubReadinessStatus.RECONNECT_REQUIRED),
        ):
            check_implementation_github_readiness(self.team.id, str(report.id))
        report.refresh_from_db()
        self.assertEqual(report.implementation_blocked_reason, "reconnect_required")
        self.assertEqual(report.implementation_blocked_at, timezone.now())
        self.assertEqual(report.status, SignalReport.Status.READY)
        with patch(
            f"{MODULE}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus.READY)
        ):
            check_implementation_github_readiness(self.team.id, str(report.id), recovery=True)
        report.refresh_from_db()
        self.assertIsNone(report.implementation_blocked_reason)

    @parameterized.expand(
        [
            ("not_connected", False, 1, False),
            ("not_connected", True, 6, True),
            ("not_connected", True, 7, False),
            ("temporarily_unavailable", False, 1, True),
        ]
    )
    def test_implementation_rechecks_only_on_reconnect_or_temporary_retry(
        self, reason: str, recovery: bool, age_days: int, resumes: bool
    ) -> None:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            implementation_blocked_reason=reason,
            implementation_blocked_at=timezone.now() - timedelta(days=age_days),
        )
        with patch(
            f"{MODULE}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus.READY)
        ) as check:
            result = check_implementation_github_readiness(self.team.id, str(report.id), recovery=recovery)
        self.assertEqual(result.status == GitHubReadinessStatus.READY, resumes)
        self.assertEqual(check.call_count, int(resumes))

    def test_recovery_rechecks_implementation_without_researching_again(self) -> None:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            implementation_blocked_reason="not_connected",
            implementation_blocked_at=timezone.now(),
        )
        with (
            patch(f"{TASKS}.self_driving_quota_gate", return_value=Mock(enforced=False)),
            patch(f"{TASKS}.daily_report_limit_gate", return_value=Mock(limited=False)),
            patch(
                f"{TASKS}.get_team_github_readiness", return_value=GitHubReadiness(status=GitHubReadinessStatus.READY)
            ),
            patch(
                "products.signals.backend.auto_start.maybe_autostart_from_report_artefacts", new_callable=AsyncMock
            ) as start,
            patch(f"{TASKS}.start_recovered_report", new_callable=AsyncMock) as research,
        ):
            resume_github_blocked_reports(self.team.id, connection_restored=True)
        assert start.await_args is not None
        self.assertEqual(start.await_args.kwargs["report_id"], str(report.id))
        research.assert_not_called()
