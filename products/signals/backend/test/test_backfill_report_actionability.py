import json
from importlib import import_module

from posthog.test.base import BaseTest

from django.apps import apps
from django.core.management import call_command
from django.db import connection

from products.signals.backend.models import SignalReport, SignalReportArtefact


class TestBackfillReportActionability(BaseTest):
    def _report(self, *, actionability: str | None) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        if actionability is not None:
            self._judgment(
                report, json.dumps({"explanation": "x", "actionability": actionability, "already_addressed": True})
            )
        return report

    def _judgment(self, report: SignalReport, content: str) -> SignalReportArtefact:
        return SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=content,
        )

    def _cached(self, report: SignalReport) -> tuple[str | None, bool | None]:
        row = SignalReport.objects.filter(id=report.id).values("latest_actionability", "latest_already_addressed")[0]
        return row["latest_actionability"], row["latest_already_addressed"]

    def test_repairs_a_report_whose_cache_disagrees_with_its_artefacts(self):
        drifted = self._report(actionability="requires_human_input")
        never_judged = self._report(actionability=None)
        SignalReport.objects.filter(id=drifted.id).update(
            latest_actionability="not_actionable", latest_already_addressed=False
        )
        SignalReport.objects.filter(id=never_judged.id).update(latest_actionability="immediately_actionable")

        call_command("backfill_report_actionability", "--team-id", str(self.team.id), "--batch-size", "1")

        assert self._cached(drifted) == ("requires_human_input", True)
        assert self._cached(never_judged) == (None, None)

    def test_migration_backfills_from_the_newest_object_shaped_judgment(self):
        judged = self._report(actionability="requires_human_input")
        newest_is_not_an_object = self._report(actionability="immediately_actionable")
        self._judgment(newest_is_not_an_object, '"not an object"')
        wrong_types = self._report(actionability=None)
        self._judgment(wrong_types, json.dumps({"actionability": 3, "already_addressed": "yes"}))
        never_judged = self._report(actionability=None)
        SignalReport.objects.filter(id__in=[judged.id, newest_is_not_an_object.id]).update(
            latest_actionability=None, latest_already_addressed=None
        )

        migration = import_module("products.signals.backend.migrations.0154_backfill_signalreport_latest_actionability")
        with connection.schema_editor() as schema_editor:
            migration.backfill_latest_actionability(apps, schema_editor)

        assert self._cached(judged) == ("requires_human_input", True)
        assert self._cached(newest_is_not_an_object) == ("immediately_actionable", True)
        assert self._cached(wrong_types) == (None, None)
        assert self._cached(never_judged) == (None, None)
