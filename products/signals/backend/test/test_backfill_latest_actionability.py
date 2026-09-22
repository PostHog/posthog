import json
import importlib

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection

from products.signals.backend.models import SignalReport, SignalReportArtefact

# The migration module name starts with a digit, so it cannot be imported by name.
backfill_migration = importlib.import_module(
    "products.signals.backend.migrations.0145_backfill_signalreport_latest_actionability"
)


class _SchemaEditor:
    connection = connection


class TestBackfillLatestActionability(BaseTest):
    def _report_with_judgments(self, *judgments: tuple[str, bool]) -> SignalReport:
        report = SignalReport.objects.create(team=self.team, status="ready", title="Report", summary="Summary")
        for actionability, already_addressed in judgments:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content=json.dumps(
                    {"explanation": "x", "actionability": actionability, "already_addressed": already_addressed}
                ),
            )
        return report

    def test_backfill_takes_the_newest_judgment_and_leaves_unjudged_reports_null(self) -> None:
        rejudged = self._report_with_judgments(("not_actionable", False), ("immediately_actionable", True))
        unjudged = self._report_with_judgments()
        SignalReport.objects.update(latest_actionability=None, latest_already_addressed=None)

        backfill_migration.backfill_latest_actionability(None, _SchemaEditor())

        rejudged.refresh_from_db()
        unjudged.refresh_from_db()
        assert rejudged.latest_actionability == "immediately_actionable"
        assert rejudged.latest_already_addressed is True
        assert unjudged.latest_actionability is None
        assert unjudged.latest_already_addressed is None

    def test_backfill_walks_past_the_first_batch(self) -> None:
        reports = [self._report_with_judgments(("not_actionable", False)) for _ in range(3)]
        SignalReport.objects.update(latest_actionability=None)

        with patch.object(backfill_migration, "BATCH_SIZE", 1):
            backfill_migration.backfill_latest_actionability(None, _SchemaEditor())

        for report in reports:
            report.refresh_from_db()
            assert report.latest_actionability == "not_actionable"
