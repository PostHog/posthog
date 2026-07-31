import uuid
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import RelatedTo
from products.signals.backend.fix_verification import (
    FIX_VERIFICATION_SOAK_WINDOW,
    evaluate_pending_fix_verifications,
    schedule_fix_verification,
)
from products.signals.backend.models import SignalFixVerification, SignalReport, SignalReportArtefact


class TestScheduleFixVerification(BaseTest):
    def _make_resolved_report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.RESOLVED,
            title="MCP tool calls failing validation",
            summary="Schema mismatch on the execute-sql tool",
        )

    def test_schedules_pending_verification_with_soak_deadline(self):
        report = self._make_resolved_report()
        task_id = uuid.uuid4()

        with freeze_time("2026-07-18T12:00:00Z"):
            verification = schedule_fix_verification(
                report, task_id=task_id, pr_url="https://github.com/posthog/posthog/pull/42"
            )

        assert verification.status == SignalFixVerification.Status.PENDING
        assert verification.task_id == task_id
        assert verification.pr_url == "https://github.com/posthog/posthog/pull/42"
        assert verification.verify_after == datetime(2026, 7, 18, 12, tzinfo=UTC) + FIX_VERIFICATION_SOAK_WINDOW
        assert verification.checked_at is None

    def test_rescheduling_same_report_is_idempotent(self):
        # GitHub redelivers webhooks; a second merge event for the same report must reuse
        # the existing row instead of crashing the webhook on the OneToOne constraint.
        report = self._make_resolved_report()

        first = schedule_fix_verification(report, task_id=uuid.uuid4(), pr_url="https://github.com/x/y/pull/1")
        second = schedule_fix_verification(report, task_id=uuid.uuid4(), pr_url="https://github.com/x/y/pull/2")

        assert first.id == second.id
        assert SignalFixVerification.objects.for_team(self.team.id).count() == 1
        assert second.pr_url == "https://github.com/x/y/pull/1"


class TestEvaluatePendingFixVerifications(BaseTest):
    _MERGED_AT = datetime(2026, 7, 1, 12, tzinfo=UTC)

    def _make_verification(self) -> tuple[SignalReport, SignalFixVerification]:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.RESOLVED,
            title="MCP tool calls failing validation",
            summary="Schema mismatch on the execute-sql tool",
        )
        with freeze_time(self._MERGED_AT):
            verification = schedule_fix_verification(
                report, task_id=uuid.uuid4(), pr_url="https://github.com/posthog/posthog/pull/42"
            )
        return report, verification

    def _spawn_recurrence(
        self, resolved: SignalReport, *, at: datetime, status: str = SignalReport.Status.POTENTIAL
    ) -> SignalReport:
        # Mirror the grouping pipeline: a signal matching a resolved report spawns a fresh
        # report and links it back via a symmetric related_to artefact pair.
        with freeze_time(at):
            recurrence = SignalReport.objects.create(
                team=self.team, status=status, title=resolved.title, summary=resolved.summary
            )
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(recurrence.id),
                content=RelatedTo(report_id=str(resolved.id)),
                attribution=ArtefactAttribution.system(),
            )
        return recurrence

    def test_recurrence_settles_regressed_before_the_deadline(self):
        resolved, verification = self._make_verification()
        recurrence = self._spawn_recurrence(resolved, at=self._MERGED_AT + timedelta(days=2))

        now = self._MERGED_AT + timedelta(days=3)
        stats = evaluate_pending_fix_verifications(now=now)

        verification.refresh_from_db()
        assert verification.status == SignalFixVerification.Status.REGRESSED
        assert verification.regressed_report_id == recurrence.id
        assert verification.checked_at == now
        assert stats.regressed == 1

    def test_quiet_report_verifies_at_the_deadline(self):
        _, verification = self._make_verification()

        stats = evaluate_pending_fix_verifications(now=self._MERGED_AT + FIX_VERIFICATION_SOAK_WINDOW)

        verification.refresh_from_db()
        assert verification.status == SignalFixVerification.Status.VERIFIED
        assert verification.checked_at is not None
        assert stats.verified == 1

    def test_not_due_stays_pending(self):
        _, verification = self._make_verification()

        stats = evaluate_pending_fix_verifications(now=self._MERGED_AT + timedelta(days=1))

        verification.refresh_from_db()
        assert verification.status == SignalFixVerification.Status.PENDING
        assert verification.checked_at is None
        assert stats.checked == 0

    def test_dismissed_recurrence_does_not_regress(self):
        # A recurrence the team dismissed as noise must not fail the fix; quiet-through-soak wins.
        resolved, verification = self._make_verification()
        self._spawn_recurrence(resolved, at=self._MERGED_AT + timedelta(days=2), status=SignalReport.Status.SUPPRESSED)

        evaluate_pending_fix_verifications(now=self._MERGED_AT + FIX_VERIFICATION_SOAK_WINDOW)

        verification.refresh_from_db()
        assert verification.status == SignalFixVerification.Status.VERIFIED

    def test_related_link_predating_the_fix_does_not_count(self):
        # The resolved report may itself have been born as a recurrence of an older report;
        # that pre-merge link must not read as post-merge recurrence.
        resolved, verification = self._make_verification()
        self._spawn_recurrence(resolved, at=self._MERGED_AT - timedelta(days=5))

        evaluate_pending_fix_verifications(now=self._MERGED_AT + FIX_VERIFICATION_SOAK_WINDOW)

        verification.refresh_from_db()
        assert verification.status == SignalFixVerification.Status.VERIFIED

    def test_report_that_left_resolved_settles_inconclusive(self):
        resolved, verification = self._make_verification()
        resolved.status = SignalReport.Status.SUPPRESSED
        resolved.save(update_fields=["status"])

        stats = evaluate_pending_fix_verifications(now=self._MERGED_AT + FIX_VERIFICATION_SOAK_WINDOW)

        verification.refresh_from_db()
        assert verification.status == SignalFixVerification.Status.INCONCLUSIVE
        assert stats.inconclusive == 1
