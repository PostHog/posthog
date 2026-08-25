from posthog.test.base import BaseTest

from products.signals.backend.models import SignalReport
from products.signals.backend.serializers import SignalReportSerializer


class TestReportPresentationFields(BaseTest):
    def _report(self, status: SignalReport.Status = SignalReport.Status.IN_PROGRESS) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=status)

    def test_ready_transition_writes_presentation_fields(self) -> None:
        report = self._report()
        updated = report.transition_to(
            SignalReport.Status.READY,
            title="fix(checkout): handle expired sessions",
            summary="Users hit a dead end.\n\n## Problem\n...",
            headline="Users hit a dead end on expired checkout sessions.",
            impact="Around 40 checkouts a day end in an error page.",
            recommended_action="Ship the session-refresh fix.",
        )
        report.save(update_fields=updated)
        report.refresh_from_db()
        assert report.headline == "Users hit a dead end on expired checkout sessions."
        assert report.impact == "Around 40 checkouts a day end in an error page."
        assert report.recommended_action == "Ship the session-refresh fix."

    def test_rewrite_without_presentation_fields_withdraws_them(self) -> None:
        # A re-research whose output omits the fields (an older workflow replay, or an
        # agent that returned none) must not leave stale one-liners describing the
        # previous summary beside the new one.
        report = self._report()
        report.save(
            update_fields=report.transition_to(
                SignalReport.Status.READY,
                title="t",
                summary="s",
                headline="Old headline",
                impact="Old impact",
                recommended_action="Old action",
            )
        )
        report.save(update_fields=report.transition_to(SignalReport.Status.CANDIDATE))
        report.save(update_fields=report.transition_to(SignalReport.Status.IN_PROGRESS))
        report.save(update_fields=report.transition_to(SignalReport.Status.READY, title="t2", summary="s2"))
        report.refresh_from_db()
        assert report.headline is None
        assert report.impact is None
        assert report.recommended_action is None

    def test_update_authored_content_sets_changed_fields_and_noops_identical(self) -> None:
        report = self._report(SignalReport.Status.READY)
        report.title = "t"
        report.summary = "s"
        report.headline = "Same headline"
        report.save()

        assert report.update_authored_content(headline="Same headline") == []
        updated = report.update_authored_content(headline="New headline", impact="New impact")
        assert set(updated) == {"headline", "impact", "updated_at"}
        report.save(update_fields=updated)
        report.refresh_from_db()
        assert report.headline == "New headline"
        assert report.impact == "New impact"

    def test_serializer_exposes_presentation_fields(self) -> None:
        report = self._report(SignalReport.Status.READY)
        report.headline = "One-line verdict"
        report.save()
        data = SignalReportSerializer(report).data
        assert data["headline"] == "One-line verdict"
        assert data["impact"] is None
        assert data["recommended_action"] is None
