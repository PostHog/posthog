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

    def _append_priority(self, report: SignalReport, priority: str) -> SignalReportArtefact:
        return SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": priority, "explanation": "because"}),
        )

    # --- classification ---

    def test_status_and_log_types_are_disjoint(self):
        assert SignalReportArtefact.STATUS_ARTEFACT_TYPES.isdisjoint(SignalReportArtefact.LOG_ARTEFACT_TYPES)

    def test_agentic_set_never_touches_log_types(self):
        # The agentic pipeline appends _AGENTIC_ARTEFACT_TYPES versions on every run. The set must
        # stay disjoint from the log types so the two write paths never collide on a type.
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

    # --- append_status ---

    def test_append_status_appends_each_version(self):
        report = self._report()
        first = self._append_priority(report, "P2")
        second = self._append_priority(report, "P0")

        # Distinct rows — the prior version is retained as history, not overwritten.
        assert first.id != second.id
        rows = SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        ).order_by("created_at")
        assert rows.count() == 2
        # Current status is the latest row.
        assert json.loads(rows[1].content)["priority"] == "P0"

    def test_append_status_rejects_log_type(self):
        report = self._report()
        with self.assertRaises(ValueError):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(report.id),
                type=SignalReportArtefact.ArtefactType.NOTE,
                content=json.dumps({"note": "x"}),
            )

    # --- append_finding ---

    def test_append_finding_appends_signal_finding(self):
        report = self._report()
        first = SignalReportArtefact.append_finding(
            team_id=self.team.id, report_id=str(report.id), content=json.dumps({"signal_id": "s1"})
        )
        second = SignalReportArtefact.append_finding(
            team_id=self.team.id, report_id=str(report.id), content=json.dumps({"signal_id": "s2"})
        )

        assert first.type == SignalReportArtefact.ArtefactType.SIGNAL_FINDING
        assert first.id != second.id
        assert (
            SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING
            ).count()
            == 2
        )

    # --- update_content ---

    def test_update_content_replaces_and_stamps_updated_at(self):
        report = self._report()
        artefact = self._add_log(report, "before")
        artefact.update_content(json.dumps({"note": "after"}))

        artefact.refresh_from_db()
        assert json.loads(artefact.content) == {"note": "after"}
        assert artefact.updated_at is not None
