from __future__ import annotations

from posthog.test.base import APIBaseTest

from products.signals.backend.models import SignalReport, SignalScoutNote
from products.signals.backend.reviewer_correction_notes import ReviewerCorrection, forward_reviewer_correction_note


class TestReviewerCorrectionScoutNotes(APIBaseTest):
    def _create_report(self, title: str = "Checkout errors spiked") -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title=title, summary="s")

    def _correction_notes(self) -> list[SignalScoutNote]:
        return list(
            SignalScoutNote.objects.filter(
                team=self.team, origin=SignalScoutNote.Origin.REPORT_REVIEWER_CORRECTION
            ).order_by("created_at")
        )

    def _forward(self, report: SignalReport, *, added: tuple[str, ...], removed: tuple[str, ...]) -> None:
        forward_reviewer_correction_note(
            team=self.team,
            correction=ReviewerCorrection(
                report_id=str(report.id),
                added_logins=added,
                removed_logins=removed,
                actor_user_id=self.user.id,
                scoped_team_ids=None,
            ),
        )

    def test_reversal_within_window_still_forwards(self) -> None:
        # Suppression is per direction: an addition must not swallow a later removal of the same login
        # inside the window — that reversal is exactly the stale-routing correction the channel exists
        # for. Both edits land on the same report, so they hit the same (fleet-wide) target.
        report = self._create_report()

        self._forward(report, added=("alice",), removed=())
        self._forward(report, added=(), removed=("alice",))

        notes = self._correction_notes()
        assert len(notes) == 2
        assert "Added: `alice`" in notes[0].content
        assert "Removed: `alice`" in notes[1].content

    def test_same_direction_repeat_is_coalesced(self) -> None:
        # The deliberate coalescing still holds: one person trimming the same login off two reports in
        # the window tells each scout once, since both edits are the same direction to the same target.
        report_a = self._create_report(title="report A")
        report_b = self._create_report(title="report B")

        self._forward(report_a, added=(), removed=("alice",))
        self._forward(report_b, added=(), removed=("alice",))

        notes = self._correction_notes()
        assert len(notes) == 1
        assert "Removed: `alice`" in notes[0].content
