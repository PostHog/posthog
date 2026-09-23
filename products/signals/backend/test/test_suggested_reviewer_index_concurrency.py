"""Two rebuilds of one report's reviewer index, forced to overlap over separate connections."""

import json
import threading

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import patch

from django.db import connection

from products.signals.backend import suggested_reviewer_index
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportSuggestedReviewer
from products.signals.backend.suggested_reviewer_index import sync_suggested_reviewer_index


class TestSuggestedReviewerIndexConcurrency(NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _create_report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Test report",
            summary="Test summary",
            signal_count=1,
            total_weight=1.0,
        )

    def _name_reviewer(self, report: SignalReport, login: str) -> None:
        SignalReportArtefact.objects.create(
            team=report.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": login}]),
        )

    def _indexed_logins(self, report: SignalReport) -> set[str | None]:
        return set(
            SignalReportSuggestedReviewer.all_teams.filter(report_id=report.id).values_list("github_login", flat=True)
        )

    def test_a_rebuild_that_waits_for_the_lock_reads_the_artefacts_again(self) -> None:
        report = self._create_report()
        self._name_reviewer(report, "alice")
        take_lock = suggested_reviewer_index._lock_report
        intercepted: list[bool] = []

        def replace_the_reviewer() -> None:
            try:
                self._name_reviewer(report, "bob")
            finally:
                connection.close()

        def let_the_other_writer_finish_first(team_id: int, report_id: str) -> None:
            # Stands in for the winning rebuild committing while this one waits for the lock. The
            # replacement runs a rebuild of its own, which re-enters this patch, so it must only
            # spawn the writer on the outer call.
            if not intercepted:
                intercepted.append(True)
                writer = threading.Thread(target=replace_the_reviewer)
                writer.start()
                writer.join(timeout=30)
                self.assertFalse(writer.is_alive())
            take_lock(team_id, report_id)

        with patch.object(suggested_reviewer_index, "_lock_report", side_effect=let_the_other_writer_finish_first):
            sync_suggested_reviewer_index(team_id=self.team.id, report_id=str(report.id))

        self.assertEqual(self._indexed_logins(report), {"bob"})
