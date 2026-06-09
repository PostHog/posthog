import json

from posthog.test.base import BaseTest

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.temporal.agentic.report import _AGENTIC_ARTEFACT_TYPES


class TestSignalReportArtefactHelpers(BaseTest):
    def _report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )

    def _add_log(self, report: SignalReport, note: str = "x") -> SignalReportArtefact:
        return SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=json.dumps({"note": note}),
        )

    def _upsert_priority(self, report: SignalReport, priority: str) -> SignalReportArtefact:
        return SignalReportArtefact.upsert_status(
            team_id=self.team.id,
            report_id=str(report.id),
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": priority, "explanation": "because"}),
        )

    # --- classification ---

    def test_status_and_log_types_are_disjoint(self):
        assert SignalReportArtefact.STATUS_ARTEFACT_TYPES.isdisjoint(SignalReportArtefact.LOG_ARTEFACT_TYPES)

    def test_agentic_replace_set_never_touches_log_types(self):
        # The agentic pipeline bulk deletes+recreates _AGENTIC_ARTEFACT_TYPES on every run. If a
        # log type ever leaked into that set, re-promotion would wipe agent-authored work-log entries.
        assert set(_AGENTIC_ARTEFACT_TYPES).isdisjoint(SignalReportArtefact.LOG_ARTEFACT_TYPES)

    # --- add_log ---

    def test_add_log_appends(self):
        report = self._report()
        first = self._add_log(report, "one")
        second = self._add_log(report, "two")

        assert first.id != second.id
        notes = list(
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.NOTE).order_by(
                "created_at"
            )
        )
        assert [json.loads(n.content)["note"] for n in notes] == ["one", "two"]

    def test_add_log_rejects_status_type(self):
        report = self._report()
        with self.assertRaises(ValueError):
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(report.id),
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content=json.dumps({"priority": "P1"}),
            )

    # --- upsert_status ---

    def test_upsert_status_creates_then_replaces_in_place(self):
        report = self._report()
        created = self._upsert_priority(report, "P2")
        updated = self._upsert_priority(report, "P0")

        # Same row, content replaced, exactly one row of this type.
        assert created.id == updated.id
        rows = SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        )
        assert rows.count() == 1
        assert json.loads(rows.first().content)["priority"] == "P0"

    def test_upsert_status_collapses_pre_existing_duplicates(self):
        report = self._report()
        # Two duplicate rows can exist from before the singleton helper landed.
        for priority in ("P1", "P2"):
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content=json.dumps({"priority": priority}),
            )

        self._upsert_priority(report, "P0")

        rows = SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        )
        assert rows.count() == 1
        assert json.loads(rows.first().content)["priority"] == "P0"

    def test_upsert_status_rejects_log_type(self):
        report = self._report()
        with self.assertRaises(ValueError):
            SignalReportArtefact.upsert_status(
                team_id=self.team.id,
                report_id=str(report.id),
                type=SignalReportArtefact.ArtefactType.NOTE,
                content=json.dumps({"note": "x"}),
            )

    # --- update_content ---

    def test_update_content_replaces_and_stamps_updated_at(self):
        report = self._report()
        artefact = self._add_log(report, "before")
        artefact.update_content(json.dumps({"note": "after"}))

        artefact.refresh_from_db()
        assert json.loads(artefact.content) == {"note": "after"}
        assert artefact.updated_at is not None
