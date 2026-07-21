import uuid
from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest

from products.signals.backend.fix_verification import FIX_VERIFICATION_SOAK_WINDOW, schedule_fix_verification
from products.signals.backend.models import SignalFixVerification, SignalReport


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
