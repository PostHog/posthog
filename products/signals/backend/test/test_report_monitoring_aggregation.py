import json
import time
from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckResult
from products.signals.backend.facade.api import organization_acted_on_report
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
    SignalReportTrackerIssue,
)
from products.signals.backend.report_monitoring_aggregation import (
    MonitoringAggregation,
    MonitoringMemberState,
    aggregate_monitoring_members,
)
from products.signals.backend.report_monitoring_attempts import complete_implementation
from products.signals.backend.report_monitoring_outcomes import (
    aggregate_due_monitoring_attempts,
    aggregate_monitoring_attempt,
)
from products.signals.backend.report_monitoring_results import MonitoringEvaluation, save_monitoring_result
from products.signals.backend.tracker_issues import complete_monitoring_tracker_issues


class TestMonitoringAggregation(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_snapshot_is_not_success", (), "waiting"),
            ("all_passed", ("passed", "passed"), "passed"),
            ("pass_does_not_hide_pending_member", ("passed", "waiting"), "waiting"),
            ("failure_preempts_pending_members", ("waiting", "failed"), "failed"),
            ("failure_preempts_assessment", ("inconclusive", "failed", "exhausted"), "failed"),
            ("assessment_waits_for_other_checks", ("inconclusive", "waiting"), "waiting"),
            ("insufficient_evidence_needs_assessment", ("passed", "inconclusive"), "assessment_required"),
            ("exhausted_errors_are_not_failure", ("passed", "exhausted"), "assessment_required"),
        ]
    )
    def test_outcome_priority(self, _name: str, members: tuple[str, ...], expected: str) -> None:
        assert aggregate_monitoring_members(tuple(MonitoringMemberState(member) for member in members)) == (
            MonitoringAggregation(expected)
        )


class TestReportMonitoringAggregation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.enterContext(time_machine.travel(self.now, tick=False))
        self.flag = self.enterContext(
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
        )
        self.close_tracker = self.enterContext(
            patch("products.signals.backend.tracker_issues.close_tracker_issue_for_report", return_value=True)
        )
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Checkout recovery"
        )
        self.checks = [self._check(), self._check(soak_minutes=120)]
        self.attempt = complete_implementation(
            team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now - timedelta(hours=2)
        )
        assert self.attempt is not None
        self.report.refresh_from_db()

    def _check(self, *, soak_minutes: int = 60) -> SignalReportCheck:
        return SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Successful checkouts",
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            config={},
            soak_minutes=soak_minutes,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=30),
            runs_remaining=3,
        )

    def _evaluation(self, index: int, outcome: str = "passed") -> MonitoringEvaluation:
        check = self.checks[index]
        assert self.attempt is not None and check.soak_minutes is not None
        sufficient = outcome in {"passed", "failed"}
        return MonitoringEvaluation(
            team_id=self.team.id,
            report_id=self.report.id,
            attempt_id=self.attempt.id,
            check_id=check.id,
            submission_id=uuid4(),
            definition_version=self.attempt.check_versions[str(check.id)],
            window_start=self.attempt.monitoring_started_at,
            window_end=self.attempt.monitoring_started_at + timedelta(minutes=check.soak_minutes),
            evaluated_at=self.now,
            evidence_status="sufficient" if sufficient else "errored" if outcome == "errored" else "insufficient",
            evidence_reason="qualifying_observations" if sufficient else "unavailable_evidence",
            expectation_matches=outcome == "passed" if sufficient else None,
            explanation="The fixed-window observation supports this result.",
            evidence_refs=("observation:example",),
        )

    def _aggregate(self) -> MonitoringAggregation:
        assert self.attempt is not None
        return aggregate_monitoring_attempt(team_id=self.team.id, report_id=self.report.id, attempt_id=self.attempt.id)

    def test_all_members_must_pass_and_unsnapshotted_checks_cannot_hold_completion(self) -> None:
        extra = self._check()
        historical = self._check()
        historical.status = SignalReportCheck.Status.EXPIRED
        historical.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            first = save_monitoring_result(self._evaluation(0))
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        self.checks[0].refresh_from_db()
        assert self.checks[0].status == SignalReportCheck.Status.PASSED
        assert SignalReportArtefact.objects.filter(report=self.report, type="check_result").count() == 1
        self._aggregate()
        assert SignalReportArtefact.objects.filter(report=self.report, type="check_result").count() == 1
        final = self._evaluation(1)
        with self.captureOnCommitCallbacks(execute=True):
            second = save_monitoring_result(final)
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED
        assert self.attempt is not None
        self.attempt.refresh_from_db()
        assert self.attempt.aggregation_state == "passed"
        assert self.attempt.aggregation_result_ids is not None
        assert set(self.attempt.aggregation_result_ids) == {str(first.id), str(second.id)}
        assert self.attempt.research_requested_at is None and self.attempt.assessment_requested_at is None
        assert set(
            SignalReportCheck.objects.for_team(self.team.id)
            .filter(id__in=[c.id for c in self.checks])
            .values_list("status", flat=True)
        ) == {"passed"}
        extra.refresh_from_db()
        assert extra.status == "cancelled"
        assert save_monitoring_result(final).id == second.id
        assert SignalReportCheck.objects.for_team(self.team.id).filter(runs_remaining=3).count() == 4
        historical.refresh_from_db()
        assert historical.status == SignalReportCheck.Status.EXPIRED
        self.close_tracker.assert_not_called()
        complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        self.close_tracker.assert_called_once_with(
            report_id=str(self.report.id),
            team_id=self.team.id,
            completed=True,
            monitoring_attempt_id=str(self.attempt.id),
            priority=Priority.BATCH,
        )

    def test_failure_closes_immediately_and_records_research_intent_atomically(self) -> None:
        earlier = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=CheckResult(
                check_id=str(self.checks[0].id),
                kind=self.checks[0].kind,
                title=self.checks[0].title,
                outcome="passed",
                explanation="An earlier observation passed.",
            ),
            attribution=ArtefactAttribution.system(),
        )
        SignalReportArtefact.objects.filter(id=earlier.id, team_id=self.team.id).update(
            created_at=self.now - timedelta(hours=1)
        )
        self.checks[0].last_run_at = self.now - timedelta(hours=1)
        self.checks[0].save(update_fields=["last_run_at"])
        self.checks[1].soak_minutes = 240
        self.checks[1].save(update_fields=["soak_minutes"])
        with self.captureOnCommitCallbacks(execute=True):
            save_monitoring_result(self._evaluation(0, "failed"))
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.CLOSED
        assert organization_acted_on_report(self.organization.id)
        assert self.report.error is None
        assert self.attempt is not None
        self.attempt.refresh_from_db()
        assert self.attempt.aggregation_state == "failed"
        assert self.attempt.research_requested_at == self.now
        assert self.attempt.assessment_requested_at is None
        self.checks[1].refresh_from_db()
        assert self.checks[1].status == "cancelled"
        assert self._aggregate() == MonitoringAggregation.WAITING
        assert SignalReportArtefact.objects.filter(report=self.report, type="note").count() == 1
        latest = SignalReportArtefact.objects.filter(report=self.report, type="check_result").latest("created_at")
        content = json.loads(latest.content)
        assert content["outcome"] == "failed"
        assert content["explanation"] == self._evaluation(0, "failed").explanation
        assert SignalReportArtefact.objects.filter(report=self.report, type="check_result").count() == 2
        self.checks[0].refresh_from_db()
        assert self.checks[0].last_run_at == self.now
        self.close_tracker.assert_not_called()

    @parameterized.expand([("insufficient",), ("errored",)])
    def test_assessment_waits_for_settlement_and_is_requested_once(self, outcome: str) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            save_monitoring_result(self._evaluation(0, outcome))
        assert self.attempt is not None
        self.attempt.refresh_from_db()
        assert self.attempt.assessment_requested_at is None
        if outcome == "errored":
            for _ in range(2):
                with self.captureOnCommitCallbacks(execute=True):
                    save_monitoring_result(self._evaluation(0, outcome))
        with self.captureOnCommitCallbacks(execute=True):
            save_monitoring_result(self._evaluation(1))
        self.attempt.refresh_from_db()
        self.report.refresh_from_db()
        assert self.attempt.aggregation_state == "assessment_required"
        assert self.attempt.assessment_requested_at == self.now
        assert self.attempt.research_requested_at is None
        assert self.report.status == SignalReport.Status.MONITORING
        self.checks[1].refresh_from_db()
        assert self.checks[1].status == SignalReportCheck.Status.PASSED
        self._aggregate()
        assert SignalReportArtefact.objects.filter(report=self.report, type="note").count() == 1
        with self.captureOnCommitCallbacks(execute=True):
            save_monitoring_result(self._evaluation(0, "failed"))
        self.attempt.refresh_from_db()
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.CLOSED
        assert self.attempt.assessment_requested_at == self.now
        assert self.attempt.research_requested_at == self.now

    @parameterized.expand([("provider_failure",), ("missed_sweep",)])
    def test_tracker_completion_recovers_after_report_resolution(self, cause: str) -> None:
        self.close_tracker.return_value = False
        SignalReportTrackerIssue.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            provider="github",
            status=SignalReportTrackerIssue.Status.CREATED,
        )
        with self.captureOnCommitCallbacks(execute=True):
            save_monitoring_result(self._evaluation(0))
            save_monitoring_result(self._evaluation(1))
            self._aggregate()
        assert self.attempt is not None
        self.attempt.refresh_from_db()
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED
        assert self.attempt.tracker_issue_close_requested_at == self.now
        assert self.attempt.tracker_issue_close_processed_at is None
        self.close_tracker.assert_not_called()
        aggregate_due_monitoring_attempts(deadline=time.monotonic() + 30, limit=10)
        self.close_tracker.assert_not_called()
        if cause == "provider_failure":
            complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
            self.attempt.refresh_from_db()
            assert self.attempt.tracker_issue_close_processed_at is None
        initial_calls = self.close_tracker.call_count
        self.close_tracker.return_value = True
        retry_at = self.now + timedelta(minutes=5) if cause == "provider_failure" else self.now
        with time_machine.travel(retry_at, tick=False):
            complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        self.attempt.refresh_from_db()
        assert self.attempt.tracker_issue_close_processed_at == retry_at
        assert self.close_tracker.call_count == initial_calls + 1
        complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        assert self.close_tracker.call_count == initial_calls + 1

    def test_failed_tracker_batch_does_not_starve_new_requests(self) -> None:
        self.close_tracker.return_value = False
        SignalReportTrackerIssue.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            status=SignalReportTrackerIssue.Status.CREATED,
        )
        attempts = [
            SignalReportMonitoringAttempt(
                team_id=self.team.id,
                report=self.report,
                monitoring_started_at=self.now - timedelta(days=200 - index),
                tracker_issue_close_requested_at=self.now - timedelta(hours=1) + timedelta(seconds=index),
            )
            for index in range(101)
        ]
        SignalReportMonitoringAttempt.objects.for_team(self.team.id).bulk_create(attempts)
        complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        assert self.close_tracker.call_count == 100
        complete_monitoring_tracker_issues(deadline=time.monotonic() + 30)
        assert self.close_tracker.call_count == 101
        assert self.close_tracker.call_args.kwargs["monitoring_attempt_id"] == str(attempts[-1].id)

    @parameterized.expand(
        [
            ("suppressed",),
            ("resolved",),
            ("reopened",),
            ("disabled",),
            ("changed_definition",),
            ("cancelled",),
            ("missing_member",),
        ]
    )
    def test_recovery_cannot_apply_stale_or_incomplete_evidence(self, change: str) -> None:
        save_monitoring_result(self._evaluation(0))
        save_monitoring_result(self._evaluation(1))
        if change in {"suppressed", "resolved", "reopened"}:
            target = {"suppressed": "suppressed", "resolved": "resolved", "reopened": "ready"}[change]
            self.report.save(update_fields=self.report.transition_to(SignalReport.Status(target)))
        elif change == "disabled":
            self.flag.return_value = False
        elif change == "changed_definition":
            SignalReportCheck.objects.for_team(self.team.id).filter(id=self.checks[1].id).update(
                title="A different expectation"
            )
        elif change == "cancelled":
            SignalReportCheck.objects.for_team(self.team.id).filter(id=self.checks[1].id).update(status="cancelled")
        else:
            self.checks[1].delete()
        prior_status = self.report.status
        aggregate_due_monitoring_attempts(deadline=time.monotonic() + 30, limit=10)
        self.report.refresh_from_db()
        assert self.report.status == prior_status
        assert self.attempt is not None
        self.attempt.refresh_from_db()
        assert self.attempt.assessment_requested_at is None and self.attempt.research_requested_at is None

    def test_lost_callback_is_recovered_and_other_teams_cannot_complete_it(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            save_monitoring_result(self._evaluation(0))
        save_monitoring_result(self._evaluation(1, "failed"))
        other = Team.objects.create(organization=self.organization)
        assert self.attempt is not None
        assert (
            aggregate_monitoring_attempt(team_id=other.id, report_id=self.report.id, attempt_id=self.attempt.id)
            == MonitoringAggregation.WAITING
        )
        aggregate_due_monitoring_attempts(deadline=time.monotonic() + 30, limit=10)
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.CLOSED

    def test_rolled_back_result_cannot_leave_a_request_or_transition(self) -> None:
        with self.assertRaises(RuntimeError), self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                save_monitoring_result(self._evaluation(0, "failed"))
                self._aggregate()
                raise RuntimeError("Abort the enclosing write")
        self.report.refresh_from_db()
        assert self.attempt is not None
        self.attempt.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        assert self.attempt.research_requested_at is None
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
