from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.signals.backend.models import SignalReport, SignalReportAssignment
from products.signals.backend.report_inbox_state import reconcile_report_inbox_state


class TestBackfillReportInboxState(BaseTest):
    def _report(self) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="t", summary="s")

    def _flags(self, report: SignalReport) -> tuple[bool, bool]:
        row = SignalReport.objects.filter(id=report.id).values_list(
            "has_implementation_pr", "has_active_implementation_pr"
        )[0]
        return row[0], row[1]

    def test_corrects_implementation_pr_flags_that_disagree_with_the_links(self) -> None:
        open_pr = self._report()
        merged_pr = self._report()
        stale = self._report()
        for report, number, merged in ((open_pr, 1, False), (merged_pr, 2, True)):
            SignalReportAssignment.all_teams.create(
                team=self.team,
                report=report,
                pr_url=f"https://github.com/example/app/pull/{number}",
                repository="example/app",
                pr_number=number,
                pr_state="merged" if merged else "open",
                pr_merged=merged,
            )
        SignalReport.objects.filter(id__in=[open_pr.id, merged_pr.id]).update(
            has_implementation_pr=False, has_active_implementation_pr=False
        )
        SignalReport.objects.filter(id=stale.id).update(has_implementation_pr=True, has_active_implementation_pr=True)

        call_command(
            "backfill_report_inbox_state",
            "--team-id",
            str(self.team.id),
            "--batch-size",
            "2",
        )

        assert self._flags(open_pr) == (True, True)
        assert self._flags(merged_pr) == (True, False)
        assert self._flags(stale) == (False, False)

    def test_reconcile_counts_and_corrects_rows_a_bulk_write_left_stale(self) -> None:
        linked = [self._report(), self._report()]
        SignalReportAssignment.all_teams.bulk_create(
            [
                SignalReportAssignment(
                    team=self.team,
                    report=report,
                    pr_url=f"https://github.com/example/app/pull/{number}",
                    repository="example/app",
                    pr_number=number,
                    pr_state="open",
                )
                for number, report in enumerate(linked, start=3)
            ]
        )

        with patch("products.signals.backend.report_inbox_state._RECONCILE_BATCH_SIZE", 1):
            assert reconcile_report_inbox_state(self.team.id) == 2
        assert [self._flags(report) for report in linked] == [(True, True), (True, True)]
        assert reconcile_report_inbox_state(self.team.id) == 0
