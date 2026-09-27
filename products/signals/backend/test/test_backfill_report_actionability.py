import json
import importlib
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command

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
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content=json.dumps(
                    {"explanation": "x", "actionability": actionability, "already_addressed": True},
                ),
            )
        return report

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

    def _judgment(self, report: SignalReport, *, content: str, created_at: datetime) -> None:
        artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=content,
        )
        SignalReportArtefact.objects.filter(id=artefact.id).update(created_at=created_at)

    def test_migration_fills_reports_judged_before_the_columns_existed(self):
        judged = self._report(actionability=None)
        self._judgment(
            judged,
            content=json.dumps({"actionability": "not_actionable", "already_addressed": False}),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self._judgment(
            judged,
            content=json.dumps({"actionability": "immediately_actionable", "already_addressed": True}),
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        self._judgment(judged, content="not json", created_at=datetime(2026, 1, 3, tzinfo=UTC))
        other = self._report(actionability=None)
        self._judgment(
            other,
            content=json.dumps({"actionability": "requires_human_input", "already_addressed": False}),
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        unjudged = self._report(actionability=None)
        # The receivers keep the columns current today, so clearing them is what a report judged
        # before those columns existed looks like.
        SignalReport.objects.all().update(latest_actionability=None, latest_already_addressed=None)

        migration = importlib.import_module("products.signals.backend.migrations.0154_backfill_report_actionability")
        migration.backfill_report_actionability(apps, None)

        assert self._cached(judged) == ("immediately_actionable", True)
        assert self._cached(other) == ("requires_human_input", False)
        assert self._cached(unjudged) == (None, None)

    def test_migration_keeps_a_judgment_stored_after_its_artefact_read(self):
        report = self._report(actionability=None)
        self._judgment(
            report,
            content=json.dumps({"actionability": "not_actionable", "already_addressed": False}),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        SignalReport.objects.all().update(latest_actionability=None, latest_already_addressed=None)
        migration = importlib.import_module("products.signals.backend.migrations.0154_backfill_report_actionability")
        latest_judgment = migration._latest_judgment

        def judged_again_before_the_update(*args, **kwargs):
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content=json.dumps({"actionability": "immediately_actionable", "already_addressed": True}),
            )
            return latest_judgment(*args, **kwargs)

        with patch.object(migration, "_latest_judgment", side_effect=judged_again_before_the_update):
            migration.backfill_report_actionability(apps, None)

        assert self._cached(report) == ("immediately_actionable", True)
