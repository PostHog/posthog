from io import StringIO

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.core.management import call_command

from products.signals.backend.models import SignalReport


class TestBackfillReportCanvases(APIBaseTest):
    def _report(self, status: str) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=status,
            title=f"Report in {status}",
            signal_count=1,
            total_weight=1.0,
        )

    def test_dry_run_previews_only_the_explicit_selection(self) -> None:
        ready = self._report(SignalReport.Status.READY)
        pending_input = self._report(SignalReport.Status.PENDING_INPUT)
        self._report(SignalReport.Status.READY)
        out = StringIO()

        with patch(
            "products.signals.backend.management.commands.backfill_report_canvases.start_report_canvas_workflow",
            new_callable=AsyncMock,
        ) as start:
            call_command(
                "backfill_report_canvases",
                str(ready.id),
                str(pending_input.id),
                team_id=self.team.id,
                stdout=out,
            )

        start.assert_not_called()
        assert str(ready.id) in out.getvalue()
        assert str(pending_input.id) in out.getvalue()
        assert "2 of 2 selected reports are eligible" in out.getvalue()

    def test_execute_starts_only_selected_eligible_reports(self) -> None:
        ready = self._report(SignalReport.Status.READY)
        candidate = self._report(SignalReport.Status.CANDIDATE)
        out = StringIO()

        with patch(
            "products.signals.backend.management.commands.backfill_report_canvases.start_report_canvas_workflow",
            new_callable=AsyncMock,
            return_value=True,
        ) as start:
            call_command(
                "backfill_report_canvases",
                str(ready.id),
                str(candidate.id),
                team_id=self.team.id,
                execute=True,
                stdout=out,
            )

        start.assert_awaited_once_with(
            team_id=self.team.id,
            report_id=str(ready.id),
            notify_reviewers=False,
        )
        assert "skipped 1 ineligible reports" in out.getvalue()
