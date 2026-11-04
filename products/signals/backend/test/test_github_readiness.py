from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, Mock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.integration import Integration

from products.signals.backend.github_readiness import (
    check_report_github_readiness,
    enabled_recovery_signals,
    github_blocked_reports,
)
from products.signals.backend.github_readiness_tasks import resume_github_blocked_reports
from products.signals.backend.models import SignalReport, SignalScoutConfig
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.facade.github_readiness import get_team_github_readiness


@time_machine.travel("2026-01-01T12:00:00Z", tick=False)
class TestGitHubReadiness(BaseTest):
    @parameterized.expand([(True, True, False), (False, True, False), (True, False, False), (True, True, True)])
    def test_reconnection_recovers_only_recent_blocked_research(
        self, connected: bool, consent: bool, late_blocker: bool
    ) -> None:
        self.organization.is_ai_data_processing_approved = consent
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        blocked = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="not_connected",
            research_blocked_at=timezone.now(),
        )
        SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.PENDING_INPUT,
            research_blocked_reason="not_connected",
            research_blocked_at=timezone.now(),
        )
        SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.CANDIDATE,
            research_blocked_reason="not_connected",
            research_blocked_at=timezone.now() - timedelta(days=8),
        )
        if connected:
            Integration.objects.create(team=self.team, kind="github", integration_id="example-installation")
        client = Mock(start_workflow=AsyncMock())
        with (
            patch("products.signals.backend.github_readiness_tasks.async_connect", new=AsyncMock(return_value=client)),
            patch("products.signals.backend.github_optional.feature_enabled_or_false", return_value=False),
            patch(
                "posthog.models.integration.GitHubIntegration.sync_repository_cache",
                return_value=[{"full_name": "example/app"}],
            ),
        ):
            if late_blocker:
                with (
                    patch.object(
                        resume_github_blocked_reports, "delay", side_effect=resume_github_blocked_reports.run
                    ) as deliver,
                    self.captureOnCommitCallbacks(execute=True),
                ):
                    assert not check_report_github_readiness(self.team.id, str(blocked.id), reason="not_connected")
                deliver.assert_called_once_with(self.team.id)
            else:
                resume_github_blocked_reports(self.team.id)
        self.assertEqual(client.start_workflow.await_count, int(connected and consent))
        if connected and consent:
            args, kwargs = client.start_workflow.call_args
            self.assertEqual(args[0], "signal-report-summary")
            self.assertEqual(args[1].report_id, str(blocked.id))
            self.assertTrue(args[1].github_recovery)
            self.assertEqual(kwargs["id"], f"signals-report:{self.team.id}:{blocked.id}")

    def test_recovery_respects_source_scout_and_scanner_controls(self) -> None:
        scanner_id = "00000000-0000-4000-8000-000000000001"
        SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, skill_name="example-scout", enabled=True, emit=True
        )
        cases = [
            ("error_tracking", {}, True),
            ("linear", {}, False),
            ("signals_scout", {"skill_name": "example-scout"}, True),
            ("signals_scout", {"skill_name": "disabled-scout"}, False),
            ("replay_vision", {"scanner_id": scanner_id}, True),
            ("replay_vision", {"scanner_id": "invalid"}, False),
        ]
        signals = [
            SignalData(
                signal_id=str(index),
                source_product=product,
                source_type="example",
                source_id=str(index),
                content="Synthetic investigation evidence",
                weight=1,
                timestamp=timezone.now(),
                extra=extra,
            )
            for index, (product, extra, _) in enumerate(cases)
        ]
        with (
            patch(
                "products.signals.backend.github_readiness.SignalSourceConfig.is_source_enabled",
                side_effect=lambda team_id, product, source_type: product != "linear",
            ),
            patch("products.signals.backend.github_readiness.signal_emitting_scanner_ids", return_value={scanner_id}),
        ):
            assert enabled_recovery_signals(self.team.id, signals) == [
                signal for signal, (_, _, enabled) in zip(signals, cases) if enabled
            ]

    def test_verified_readiness_retries_an_unloaded_repository_cache(self) -> None:
        Integration.objects.create(team=self.team, kind="github", integration_id="test-installation", config={})
        with patch(
            "posthog.models.integration.GitHubIntegration.sync_repository_cache",
            return_value=[{"full_name": "example/app"}],
        ):
            assert get_team_github_readiness(self.team.id, verify=True).status == "ready"

    @parameterized.expand(
        [
            ({}, [{"full_name": "example/app"}], "", "ready"),
            ({}, [], "", "no_repositories"),
            ({"installation_unavailable_since": 1}, [], "", "reconnect_required"),
            ({}, [{"full_name": "example/app"}], "TOKEN_REFRESH_FAILED", "temporarily_unavailable"),
        ]
    )
    def test_cached_readiness_does_not_treat_loading_errors_as_reconnection(
        self, config, repositories, error, expected
    ):
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="test-installation",
            config=config,
            repository_cache=repositories,
            repository_cache_updated_at=timezone.now(),
            errors=error,
        )
        assert get_team_github_readiness(self.team.id).status == expected

    @parameterized.expand([(False, False), (True, True)])
    def test_missing_github_blocks_only_ineligible_research(self, eligible: bool, expected: bool) -> None:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.CANDIDATE)
        with patch("products.signals.backend.github_optional.feature_enabled_or_false", return_value=eligible):
            assert check_report_github_readiness(self.team.id, str(report.id)) is expected
        report.refresh_from_db()
        assert report.status == SignalReport.Status.CANDIDATE
        assert report.first_visible_at is None
        assert report.research_blocked_reason == (None if eligible else "not_connected")

    def test_recovery_is_future_only_and_does_not_extend_deadline(self) -> None:
        with time_machine.travel("2026-10-01T12:00:00Z", tick=False):
            report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.CANDIDATE)
            historical = SignalReport.objects.create(team=self.team, status=SignalReport.Status.PENDING_INPUT)
            with patch("products.signals.backend.github_optional.feature_enabled_or_false", return_value=False):
                assert not check_report_github_readiness(self.team.id, str(report.id))
            report.refresh_from_db()
            first_blocked_at = report.research_blocked_at
            assert first_blocked_at == timezone.now()
            assert set(SignalReport.objects.filter(github_blocked_reports()).values_list("id", flat=True)) == {
                report.id
            }
        with time_machine.travel("2026-10-02T12:00:00Z", tick=False):
            with patch("products.signals.backend.github_optional.feature_enabled_or_false", return_value=False):
                assert not check_report_github_readiness(self.team.id, str(report.id))
            report.refresh_from_db()
            assert report.research_blocked_at == first_blocked_at
        with time_machine.travel("2026-10-09T12:00:00Z", tick=False):
            assert not SignalReport.objects.filter(github_blocked_reports()).exists()
        historical.refresh_from_db()
        assert historical.status == SignalReport.Status.PENDING_INPUT
