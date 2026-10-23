import json
from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import (
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
)
from products.signals.backend.report_monitoring_attempts import (
    check_definition_version,
    complete_implementation,
    current_monitoring_attempt,
)

_FLAG_CLIENT = "products.signals.backend.report_content_gates.feature_enabled_or_false"


class TestMonitoringAttemptDefinitionVersion(SimpleTestCase):
    @parameterized.expand(
        [
            ("title", "Verify deployment", True),
            ("rationale", "Check the implemented change", True),
            ("kind", SignalReportCheck.Kind.METRIC_THRESHOLD, True),
            ("config", {"instructions": "Verify the new behavior"}, True),
            ("soak_minutes", 0, True),
            ("run_interval_minutes", 120, True),
            ("runs_remaining", 2, False),
            ("last_outcome", SignalReportCheck.Outcome.PASSED, False),
            ("status", SignalReportCheck.Status.ACTIVE, False),
        ]
    )
    def test_definition_versions_track_authorship_without_changing_after_execution(
        self, field: str, value: object, changes_version: bool
    ) -> None:
        check = SignalReportCheck(
            title="Verify fix",
            rationale="Confirm recovery",
            kind=SignalReportCheck.Kind.AGENT,
            config={"instructions": "Verify the behavior", "skill_name": "verification"},
            soak_minutes=60,
            run_interval_minutes=None,
            runs_remaining=3,
            status=SignalReportCheck.Status.PENDING,
        )
        before = check_definition_version(check)
        check.config = {"skill_name": "verification", "instructions": "Verify the behavior"}
        assert check_definition_version(check) == before
        setattr(check, field, value)
        assert (check_definition_version(check) != before) == changes_version


class TestReportMonitoringAttempts(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.enterContext(time_machine.travel(self.now, tick=False))
        self.flag = self.enterContext(patch(_FLAG_CLIENT, return_value=True))
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Fix checkout"
        )

    def _check(
        self,
        *,
        report: SignalReport | None = None,
        kind: str = SignalReportCheck.Kind.AGENT,
        status: str = SignalReportCheck.Status.PENDING,
        soak_minutes: int | None = 60,
    ) -> SignalReportCheck:
        report = report or self.report
        return SignalReportCheck.objects.for_team(report.team_id).create(
            team_id=report.team_id,
            report=report,
            title="Verify checkout",
            kind=kind,
            config={},
            soak_minutes=soak_minutes,
            status=status,
            next_run_at=self.now + timedelta(hours=1),
            expires_at=self.now + timedelta(days=30),
        )

    @parameterized.expand(
        [
            ("pending_agent_missing_soak", SignalReportCheck.Kind.AGENT, SignalReportCheck.Status.PENDING, None),
            ("active_agent_zero_soak", SignalReportCheck.Kind.AGENT, SignalReportCheck.Status.ACTIVE, 0),
            (
                "pending_metric_missing_definition",
                SignalReportCheck.Kind.METRIC_THRESHOLD,
                SignalReportCheck.Status.PENDING,
                60,
            ),
            (
                "active_metric_missing_soak",
                SignalReportCheck.Kind.METRIC_THRESHOLD,
                SignalReportCheck.Status.ACTIVE,
                None,
            ),
        ]
    )
    def test_open_checks_qualify_without_approval_configuration_or_positive_soak(
        self, _name: str, kind: str, status: str, soak_minutes: int | None
    ) -> None:
        check = self._check(kind=kind, status=status, soak_minutes=soak_minutes)
        start = self.now - timedelta(minutes=5)

        attempt = complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=start)

        assert attempt is not None
        assert attempt.check_versions == {str(check.id): check_definition_version(check)}
        assert attempt.monitoring_started_at == start
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        assert self.report.monitoring_started_at == start

    def test_expired_terminal_and_other_reports_checks_cannot_require_monitoring(self) -> None:
        stale = self._check(status=SignalReportCheck.Status.ACTIVE)
        stale.expires_at = self.now
        stale.save(update_fields=["expires_at"])
        terminal = self._check(status=SignalReportCheck.Status.PASSED)
        other_report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        other_check = self._check(report=other_report)

        assert (
            complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
            is None
        )

        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED
        assert not SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(report=self.report).exists()
        stale.refresh_from_db()
        terminal.refresh_from_db()
        other_check.refresh_from_db()
        assert stale.status == SignalReportCheck.Status.EXPIRED
        assert terminal.status == SignalReportCheck.Status.PASSED
        assert other_check.status == SignalReportCheck.Status.PENDING
        expired_log = SignalReportArtefact.objects.get(
            team=self.team, report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_EXPIRED
        )
        assert json.loads(expired_log.content)["check_id"] == str(stale.id)
        assert (
            complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
            is None
        )
        assert (
            SignalReportArtefact.objects.filter(
                report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_EXPIRED
            ).count()
            == 1
        )

    def test_expiry_log_failure_rolls_back_entry_and_check_changes(self) -> None:
        stale = self._check(status=SignalReportCheck.Status.ACTIVE)
        stale.expires_at = self.now
        stale.save(update_fields=["expires_at"])
        applicable = self._check(status=SignalReportCheck.Status.ACTIVE)
        with (
            patch.object(SignalReportArtefact, "add_log", side_effect=RuntimeError("Artefact storage unavailable")),
            self.assertRaisesRegex(RuntimeError, "Artefact storage unavailable"),
        ):
            complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
        self.report.refresh_from_db()
        stale.refresh_from_db()
        applicable.refresh_from_db()
        assert self.report.status == SignalReport.Status.READY
        assert stale.status == SignalReportCheck.Status.ACTIVE
        assert applicable.status == SignalReportCheck.Status.ACTIVE
        assert not SignalReportMonitoringAttempt.objects.for_team(self.team.id).exists()

    def test_child_environment_attempts_use_the_literal_team_id(self) -> None:
        child = Team.objects.create(
            organization=self.organization, parent_team=self.team, name="Verification environment"
        )
        child_report = SignalReport.objects.create(team=child, status=SignalReport.Status.READY)
        child_check = self._check(report=child_report)
        self._check()

        with self.assertRaises(SignalReport.DoesNotExist):
            complete_implementation(team_id=self.team.id, report_id=child_report.id, monitoring_started_at=self.now)
        attempt = complete_implementation(team_id=child.id, report_id=child_report.id, monitoring_started_at=self.now)

        assert attempt is not None
        assert attempt.team_id == child.id
        assert attempt.check_versions == {str(child_check.id): check_definition_version(child_check)}
        assert not SignalReportMonitoringAttempt.objects.for_team(self.team.id).exists()
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.READY

    def test_entry_rolls_back_if_monitoring_is_disabled_before_the_transition(self) -> None:
        stale = self._check(status=SignalReportCheck.Status.ACTIVE)
        stale.expires_at = self.now
        stale.save(update_fields=["expires_at"])
        applicable = self._check(status=SignalReportCheck.Status.ACTIVE)
        self.flag.side_effect = [True, False]
        with self.assertRaises(InvalidStatusTransition):
            complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
        self.report.refresh_from_db()
        stale.refresh_from_db()
        applicable.refresh_from_db()
        assert self.report.status == SignalReport.Status.READY
        assert stale.status == SignalReportCheck.Status.ACTIVE
        assert applicable.status == SignalReportCheck.Status.ACTIVE
        assert not SignalReportMonitoringAttempt.objects.for_team(self.team.id).exists()
        assert not SignalReportArtefact.objects.filter(
            report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_EXPIRED
        ).exists()

    @parameterized.expand([("disabled", False), ("unavailable", RuntimeError("flag service unavailable"))])
    def test_disabled_or_unavailable_flag_resolves_without_creating_an_attempt(
        self, _name: str, flag_result: bool | Exception
    ) -> None:
        check = self._check()
        if isinstance(flag_result, Exception):
            self.flag.side_effect = flag_result
        else:
            self.flag.return_value = flag_result

        assert (
            complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
            is None
        )

        self.report.refresh_from_db()
        check.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED
        assert self.report.monitoring_started_at is None
        assert not SignalReportMonitoringAttempt.objects.for_team(self.team.id).exists()
        assert check.status == SignalReportCheck.Status.PENDING

    @parameterized.expand(
        [("monitoring", True, True), ("manual_resolution", False, True), ("resolution", False, False)]
    )
    def test_entry_preserves_attribution_and_only_manual_resolution_closes_the_pr(
        self, _name: str, has_checks: bool, close_pr_on_resolve: bool
    ) -> None:
        if has_checks:
            self._check()
        with (
            patch("products.signals.backend.receivers.posthoganalytics.capture") as capture,
            patch("products.signals.backend.tasks.close_dismissed_report_pr.delay") as close_pr,
            self.captureOnCommitCallbacks(execute=True),
        ):
            complete_implementation(
                team_id=self.team.id,
                report_id=self.report.id,
                monitoring_started_at=self.now,
                attribution=ArtefactAttribution.from_user(self.user.id),
                actor_user=self.user,
                close_pr_on_resolve=close_pr_on_resolve,
            )
        properties = capture.call_args.kwargs["properties"]
        assert properties["actor_kind"] == "user"
        assert properties["actor_user_uuid"] == str(self.user.uuid)
        assert properties["actor_distinct_id"] == self.user.distinct_id
        if close_pr_on_resolve and not has_checks:
            close_pr.assert_called_once_with(
                report_id=str(self.report.id), team_id=self.team.id, reason="resolved", actor_user_id=self.user.id
            )
        else:
            close_pr.assert_not_called()

    def test_carried_over_check_requires_fresh_evidence_and_arms_after_commit(self) -> None:
        check = self._check(status=SignalReportCheck.Status.ACTIVE)
        old_start = self.now - timedelta(days=2)
        check.measurement_start_at = old_start
        check.last_run_at = self.now - timedelta(hours=1)
        check.last_outcome = SignalReportCheck.Outcome.INCONCLUSIVE
        check.last_outcome_reason = SignalReportCheck.InconclusiveReason.AWAITING_DATA
        check.dispatched_at = self.now - timedelta(minutes=30)
        check.consecutive_errors = 2
        check.consecutive_inconclusive = 3
        check.monitoring_fallback_expires_at = self.now + timedelta(days=5)
        check.run_interval_minutes = 120
        check.runs_remaining = 3
        check.save()
        expected_version = check_definition_version(check)

        with self.captureOnCommitCallbacks(execute=True):
            attempt = complete_implementation(
                team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now
            )
            check.refresh_from_db()
            assert check.status == SignalReportCheck.Status.PENDING
            self.assertIsNone(check.measurement_start_at)
            self.assertIsNone(check.last_run_at)
            self.assertIsNone(check.last_outcome)
            self.assertIsNone(check.last_outcome_reason)
            self.assertIsNone(check.dispatched_at)
            assert check.consecutive_errors == 0
            assert check.consecutive_inconclusive == 0
            self.assertIsNone(check.monitoring_fallback_expires_at)
            assert check.runs_remaining == 3
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.next_run_at == self.now + timedelta(hours=1)
        assert attempt is not None
        assert attempt.check_versions == {str(check.id): expected_version}

    def test_retries_and_archive_preserve_membership_but_reopening_creates_a_new_attempt(self) -> None:
        check = self._check()
        first = complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
        assert first is not None
        original_versions = first.check_versions.copy()
        check.status = SignalReportCheck.Status.CANCELLED
        check.save(update_fields=["status"])
        replacement = self._check()
        retry = complete_implementation(
            team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now - timedelta(minutes=1)
        )
        assert retry is not None
        assert retry.id == first.id
        assert retry.check_versions == original_versions
        self.report.refresh_from_db()
        self.report.save(update_fields=self.report.transition_to(SignalReport.Status.SUPPRESSED))
        archived = current_monitoring_attempt(self.report)
        assert archived is not None
        assert archived.id == first.id
        self.report.save(update_fields=self.report.transition_to(SignalReport.Status.MONITORING))
        restored = current_monitoring_attempt(self.report)
        assert restored is not None
        assert restored.id == first.id
        self.report.save(update_fields=self.report.transition_to(SignalReport.Status.READY))
        assert current_monitoring_attempt(self.report) is None

        with time_machine.travel(self.now + timedelta(hours=1), tick=False):
            second = complete_implementation(
                team_id=self.team.id,
                report_id=self.report.id,
                monitoring_started_at=self.now + timedelta(hours=1),
            )
        assert second is not None
        assert second.id != first.id
        assert second.check_versions == {str(replacement.id): check_definition_version(replacement)}
        first.refresh_from_db()
        assert first.check_versions == original_versions

    @parameterized.expand([("naive",), ("future",), ("reused",), ("older",)])
    def test_invalid_period_start_cannot_create_an_attempt_or_change_checks(self, kind: str) -> None:
        check = self._check()
        start = self.now
        if kind == "naive":
            start = timezone.make_naive(self.now)
        elif kind == "future":
            start += timedelta(seconds=1)
        else:
            SignalReportMonitoringAttempt.objects.for_team(self.team.id).create(
                team=self.team,
                report=self.report,
                monitoring_started_at=start,
                check_versions={str(check.id): check_definition_version(check)},
            )
            if kind == "older":
                start -= timedelta(seconds=1)

        with self.assertRaises(ValueError):
            complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=start)

        self.report.refresh_from_db()
        check.refresh_from_db()
        assert self.report.status == SignalReport.Status.READY
        assert check.status == SignalReportCheck.Status.PENDING
        assert SignalReportMonitoringAttempt.objects.for_team(self.team.id).count() == (
            1 if kind in {"reused", "older"} else 0
        )
