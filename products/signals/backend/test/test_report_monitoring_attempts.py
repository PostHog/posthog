import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.dbrouter import ReplicaRouter
from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckAuthoringStatus
from products.signals.backend.models import (
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_check_evaluation import CheckVerdict
from products.signals.backend.report_check_evidence import EvidenceStatus
from products.signals.backend.report_check_execution import record_check_verdict
from products.signals.backend.report_check_final_agents import monitoring_scout_check, ready_monitoring_scout_check
from products.signals.backend.report_check_final_candidates import collect_due_final_checks
from products.signals.backend.report_checks import CheckOutcome
from products.signals.backend.report_monitoring_attempts import (
    check_definition_version,
    complete_implementation,
    current_monitoring_attempt,
)
from products.signals.backend.report_monitoring_results import (
    InvalidMonitoringResult,
    MonitoringEvaluation,
    MonitoringResultConflict,
    save_monitoring_result,
)

_FLAG_CLIENT = "products.signals.backend.report_content_gates.feature_enabled_or_false"


class TestMonitoringAttemptDefinitionVersion(SimpleTestCase):
    @parameterized.expand(
        [
            ("sufficient", None, "Evidence is sufficient.", "qualified"),
            ("errored", False, "The query failed.", "query_error"),
            ("unsupported", True, "The source is unsupported.", "unsupported_source"),
            ("insufficient", False, " ", "no_activity"),
            ("insufficient", False, "No activity.", " "),
        ]
    )
    def test_invalid_evidence_cannot_claim_an_expectation_verdict(
        self, evidence_status: EvidenceStatus, matches: bool | None, explanation: str, reason: str
    ) -> None:
        now = timezone.now()
        with self.assertRaises(ValueError):
            MonitoringEvaluation(
                team_id=1,
                report_id=uuid4(),
                attempt_id=uuid4(),
                check_id=uuid4(),
                submission_id=uuid4(),
                definition_version="example",
                window_start=now,
                window_end=now,
                evaluated_at=now,
                evidence_status=evidence_status,
                evidence_reason=reason,
                expectation_matches=matches,
                explanation=explanation,
            )

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
            ("legacy_monitoring_attempt_id", uuid4(), False),
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

    def _evaluation(self, check: SignalReportCheck) -> MonitoringEvaluation:
        start = self.now - timedelta(minutes=60)
        attempt = complete_implementation(team_id=check.team_id, report_id=check.report_id, monitoring_started_at=start)
        assert attempt is not None
        return MonitoringEvaluation(
            team_id=check.team_id,
            report_id=check.report_id,
            attempt_id=attempt.id,
            check_id=check.id,
            submission_id=uuid4(),
            definition_version=check_definition_version(check),
            window_start=start,
            window_end=start + timedelta(minutes=check.soak_minutes or 0),
            evaluated_at=self.now,
            evidence_status="sufficient",
            evidence_reason="qualifying_observations",
            expectation_matches=True,
            explanation="The observed behavior meets the expectation.",
            evidence_refs=("observation:example",),
        )

    @parameterized.expand(
        [
            (f"{outcome}_{guard}", outcome, guard)
            for outcome in ["passed", "failed", "inconclusive"]
            for guard in ["unchanged", "cancelled", "manual_resolve", "unbound", "modified"]
        ]
    )
    def test_legacy_verdicts_preserve_only_their_original_monitoring_obligation(
        self, _name: str, outcome: CheckOutcome, guard: str
    ) -> None:
        check = self._check()
        check.config = {"instructions": "Verify checkout recovery."}
        check.save(update_fields=["config"])
        evaluation = self._evaluation(check)
        check.refresh_from_db()
        check.status = SignalReportCheck.Status.ACTIVE
        check.dispatched_at = self.now
        check.save(update_fields=["status", "dispatched_at"])
        if guard == "modified":
            check.title = "A revised expectation"
            check.save(update_fields=["title"])
        with patch(_FLAG_CLIENT, return_value=False):
            record_check_verdict(
                check,
                CheckVerdict(
                    outcome=outcome,
                    explanation="Legacy observation outside fixed-window verification.",
                    reason="unmeasurable" if outcome == "inconclusive" else None,
                ),
                now=self.now,
            )
        check.refresh_from_db()
        assert check.status == outcome
        assert check.legacy_monitoring_attempt_id == (None if guard == "modified" else evaluation.attempt_id)
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        assert self.report.artefacts.filter(type=SignalReportArtefact.ArtefactType.CHECK_RESULT).count() == 1
        if guard == "cancelled":
            check.status = SignalReportCheck.Status.CANCELLED
            check.save(update_fields=["status"])
        elif guard == "manual_resolve":
            self.report.refresh_from_db()
            self.report.save(update_fields=self.report.transition_to(SignalReport.Status.RESOLVED))
        elif guard == "unbound":
            check.legacy_monitoring_attempt_id = uuid4()
            check.save(update_fields=["legacy_monitoring_attempt_id"])
        due = collect_due_final_checks(self.now, kind=SignalReportCheck.Kind.AGENT, limit=10)
        if guard == "unchanged":
            assert len(due) == 1
            ready_monitoring_scout_check(monitoring_scout_check(due[0]))
            result = save_monitoring_result(evaluation)
            assert result.window_start == evaluation.window_start
            assert result.window_end == evaluation.window_end
            assert result.evidence_refs == ["observation:example"]
        else:
            assert due == []
            with self.assertRaises(InvalidMonitoringResult):
                save_monitoring_result(evaluation)

    @parameterized.expand(
        [
            (kind, status, expired)
            for kind in (SignalReportCheck.Kind.METRIC_THRESHOLD, SignalReportCheck.Kind.AGENT)
            for status, expired in (
                (SignalReportCheck.Status.PENDING, False),
                (SignalReportCheck.Status.PENDING, True),
                (SignalReportCheck.Status.ERRORED, False),
                (SignalReportCheck.Status.ERRORED, True),
                (SignalReportCheck.Status.EXPIRED, True),
            )
        ]
    )
    def test_final_result_is_durable_idempotent_and_does_not_complete_or_spend_runs(
        self, kind: str, status: str, expired: bool
    ) -> None:
        check = self._check(kind=kind)
        evaluation = self._evaluation(check)
        check.status = status
        if expired:
            check.expires_at = self.now
        check.save()

        result = save_monitoring_result(evaluation)
        assert save_monitoring_result(evaluation).id == result.id
        result.refresh_from_db()
        assert result.team_id == self.team.id
        assert result.report_id == self.report.id
        assert result.attempt_id == evaluation.attempt_id
        assert result.report_check_id == check.id
        assert result.definition_version == evaluation.definition_version
        assert result.window_start == evaluation.window_start
        assert result.window_end == evaluation.window_end
        assert result.evaluated_at == evaluation.evaluated_at
        assert result.outcome == "passed"
        assert result.evidence_status == "sufficient"
        assert result.evidence_reason == evaluation.evidence_reason
        assert result.expectation_matches is True
        assert result.explanation == evaluation.explanation
        assert result.evidence_refs == list(evaluation.evidence_refs)
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 1
        self.report.refresh_from_db()
        check.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        assert check.status == status
        assert check.runs_remaining == 1
        assert check.last_outcome is None

    @parameterized.expand([("expired",), ("resolved",), ("reopened",), ("cancelled",), ("definition",), ("disabled",)])
    def test_saved_submission_retries_survive_lifecycle_changes(self, change: str) -> None:
        check = self._check()
        evaluation = self._evaluation(check)
        result = save_monitoring_result(evaluation)
        if change in {"resolved", "reopened"}:
            self.report.refresh_from_db()
            target = SignalReport.Status.RESOLVED if change == "resolved" else SignalReport.Status.READY
            self.report.save(update_fields=self.report.transition_to(target))
        elif change == "disabled":
            self.flag.return_value = False
        else:
            if change == "expired":
                check.expires_at = self.now
            elif change == "cancelled":
                check.status = SignalReportCheck.Status.CANCELLED
            else:
                check.title = "A changed expectation"
            check.save()

        assert save_monitoring_result(evaluation).id == result.id
        with self.assertRaises(MonitoringResultConflict):
            save_monitoring_result(replace(evaluation, explanation="A different evaluation"))
        with self.assertRaises(MonitoringResultConflict if change == "expired" else InvalidMonitoringResult):
            save_monitoring_result(replace(evaluation, submission_id=uuid4()))
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 1

    def test_nonconclusive_submissions_allow_later_evaluation_and_do_not_claim_failure(self) -> None:
        evaluation = self._evaluation(self._check())
        statuses: tuple[EvidenceStatus, ...] = ("insufficient", "unsupported", "errored")
        for status in statuses:
            retry = replace(
                evaluation,
                submission_id=uuid4(),
                evidence_status=status,
                expectation_matches=False if status == "insufficient" else None,
            )
            result = save_monitoring_result(retry)
            assert save_monitoring_result(retry).id == result.id
            assert result.outcome == ("errored" if status == "errored" else "inconclusive")
        verdict = save_monitoring_result(replace(evaluation, expectation_matches=False))
        assert verdict.outcome == "failed"
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 4

    @parameterized.expand([("same_id",), ("new_id",)])
    def test_conflicting_submission_cannot_replace_a_verdict(self, change: str) -> None:
        evaluation = self._evaluation(self._check())
        result = save_monitoring_result(evaluation)
        conflict = replace(
            evaluation,
            submission_id=uuid4() if change == "new_id" else evaluation.submission_id,
            expectation_matches=False,
        )
        with self.assertRaises(MonitoringResultConflict):
            save_monitoring_result(conflict)
        result.refresh_from_db()
        assert result.outcome == "passed"
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("resolved",),
            ("suppressed",),
            ("reopened",),
            ("new_attempt",),
            ("cancelled",),
            ("passed",),
            ("failed",),
            ("inconclusive",),
            ("definition",),
            ("snapshot",),
            ("nonmember",),
            ("wrong_attempt",),
            ("wrong_team",),
            ("window_start",),
            ("window_end",),
            ("not_due",),
            ("future_evaluation",),
            ("missing_soak",),
            ("disabled",),
            ("unavailable",),
        ]
    )
    def test_invalidated_final_work_is_rejected(self, change: str) -> None:
        check = self._check(soak_minutes=None if change == "missing_soak" else 60)
        evaluation = self._evaluation(check)
        if change in {"resolved", "suppressed", "reopened", "new_attempt"}:
            self.report.refresh_from_db()
            target = {"resolved": SignalReport.Status.RESOLVED, "suppressed": SignalReport.Status.SUPPRESSED}.get(
                change, SignalReport.Status.READY
            )
            self.report.save(update_fields=self.report.transition_to(target))
            if change == "new_attempt":
                complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
        elif change in {"cancelled", "passed", "failed", "inconclusive", "definition"}:
            if change != "definition":
                check.status = change
            else:
                check.config = {"instructions": "A changed expectation"}
            check.save()
        elif change in {"snapshot", "nonmember"}:
            SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(id=evaluation.attempt_id).update(
                check_versions={} if change == "nonmember" else {str(check.id): "different-version"}
            )
        elif change == "wrong_attempt":
            evaluation = replace(evaluation, attempt_id=uuid4())
        elif change == "wrong_team":
            other_team = Team.objects.create(organization=self.organization)
            evaluation = replace(evaluation, team_id=other_team.id)
        elif change == "window_start":
            evaluation = replace(evaluation, window_start=evaluation.window_start - timedelta(seconds=1))
        elif change == "window_end":
            evaluation = replace(evaluation, window_end=evaluation.window_end - timedelta(seconds=1))
        elif change == "future_evaluation":
            evaluation = replace(evaluation, evaluated_at=self.now + timedelta(seconds=1))
        elif change == "disabled":
            self.flag.return_value = False
        elif change == "unavailable":
            self.flag.side_effect = RuntimeError("flag service unavailable")
        with time_machine.travel(self.now - timedelta(seconds=1) if change == "not_due" else self.now, tick=False):
            with self.assertRaises(InvalidMonitoringResult):
                save_monitoring_result(evaluation)
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()

    def test_zero_soak_is_immediately_due_but_does_not_imply_qualified_evidence(self) -> None:
        evaluation = self._evaluation(self._check(soak_minutes=0))
        evaluation = replace(
            evaluation,
            evaluated_at=evaluation.window_start,
            evidence_status="insufficient",
            evidence_reason="empty_window",
        )
        with time_machine.travel(evaluation.window_start, tick=False):
            result = save_monitoring_result(evaluation)
        assert result.window_start == result.window_end
        assert result.expectation_matches is True
        assert result.outcome == "inconclusive"

    def test_final_results_preserve_literal_child_environment_scoping(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        report = SignalReport.objects.create(team=child, status=SignalReport.Status.READY)
        evaluation = self._evaluation(self._check(report=report))
        result = save_monitoring_result(evaluation)
        assert result.team_id == child.id
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        assert SignalReportMonitoringResult.objects.for_team(child.id).get().id == result.id
        with self.assertRaises(InvalidMonitoringResult):
            save_monitoring_result(replace(evaluation, team_id=self.team.id))

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

    def test_authoring_failure_blocks_completion_with_replica_routing(self) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=CheckAuthoringStatus(status="failed", reason="Invalid verification proposal"),
            attribution=ArtefactAttribution.system(),
        )
        with (
            self.settings(DATABASE_ROUTERS=[ReplicaRouter(["SignalReportArtefact"])]),
            self.assertRaisesRegex(ValueError, "Follow-up check authoring failed"),
        ):
            complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=self.now)
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.READY
        assert not SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(report=self.report).exists()

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

    @parameterized.expand(
        [
            ("disabled", False),
            ("unavailable", RuntimeError("flag service unavailable")),
            ("archived_disabled", False, True),
            ("archived_unavailable", RuntimeError("flag service unavailable"), True),
        ]
    )
    def test_disabled_or_unavailable_flag_resolves_without_creating_an_attempt(
        self, _name: str, flag_result: bool | Exception, archived: bool = False
    ) -> None:
        check = self._check()
        if archived:
            self.report.save(update_fields=self.report.transition_to(SignalReport.Status.SUPPRESSED))
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
            attempt = complete_implementation(
                team_id=self.team.id,
                report_id=self.report.id,
                monitoring_started_at=self.now,
                attribution=ArtefactAttribution.from_user(self.user.id),
                actor_user=self.user,
                close_pr_on_resolve=close_pr_on_resolve,
            )
        if has_checks:
            assert attempt is not None
            assert attempt.close_pr_on_resolve == close_pr_on_resolve
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
        check.legacy_monitoring_attempt_id = uuid4()
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
            self.assertIsNone(check.legacy_monitoring_attempt_id)
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
        replacement.monitoring_dispatch_after = self.now + timedelta(days=1)
        replacement.save(update_fields=["monitoring_dispatch_after"])
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
        replacement.refresh_from_db()
        self.assertIsNone(replacement.monitoring_dispatch_after)
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
