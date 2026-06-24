import json

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    Dismissal,
    NoteArtefact,
    Priority,
    PriorityAssessment,
    SignalFinding,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.temporal.agentic.report import _AGENTIC_ARTEFACT_TYPES

# Task ORM model needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task  # tach-ignore


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

    def _task(self) -> Task:
        return Task.objects.create(
            team=self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

    def _add_log(self, report: SignalReport, note: str = "x") -> SignalReportArtefact:
        return SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=NoteArtefact(note=note),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )

    def _append_priority(self, report: SignalReport, priority: str) -> SignalReportArtefact:
        return SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=PriorityAssessment(priority=Priority(priority), explanation="because"),
            attribution=ArtefactAttribution.system(),
        )

    @staticmethod
    def _finding(signal_id: str) -> SignalFinding:
        return SignalFinding(signal_id=signal_id, relevant_code_paths=["a.py"], data_queried="none", verified=True)

    # --- classification ---

    def test_status_and_log_types_are_disjoint(self):
        assert SignalReportArtefact.STATUS_ARTEFACT_TYPES.isdisjoint(SignalReportArtefact.LOG_ARTEFACT_TYPES)

    def test_agentic_set_never_touches_log_types(self):
        # The agentic pipeline appends _AGENTIC_ARTEFACT_TYPES versions on every run. The set must
        # stay disjoint from the log types so the two write paths never collide on a type.
        assert set(_AGENTIC_ARTEFACT_TYPES).isdisjoint(SignalReportArtefact.LOG_ARTEFACT_TYPES)

    # --- attribution ---

    @parameterized.expand(
        [
            ("user_missing_id", {"kind": "user"}),
            ("user_with_task", {"kind": "user", "user_id": 1, "task_id": "t"}),
            ("task_missing_id", {"kind": "task"}),
            ("task_with_user", {"kind": "task", "task_id": "t", "user_id": 1}),
            ("system_with_user", {"kind": "system", "user_id": 1}),
            ("system_with_task", {"kind": "system", "task_id": "t"}),
        ]
    )
    def test_attribution_rejects_mismatched_fields(self, _name, kwargs):
        with self.assertRaises(ValueError):
            ArtefactAttribution(**kwargs)

    def test_user_attribution_persists_created_by(self):
        artefact = self._add_log(self._report())
        assert artefact.created_by_id == self.user.id
        assert artefact.task_id is None

    def test_task_attribution_persists_task(self):
        report = self._report()
        task = self._task()
        artefact = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(report.id),
            content=NoteArtefact(note="from an agent"),
            attribution=ArtefactAttribution.from_task(str(task.id)),
        )
        assert str(artefact.task_id) == str(task.id)
        assert artefact.created_by_id is None

    def test_system_attribution_persists_nulls(self):
        artefact = self._append_priority(self._report(), "P1")
        assert artefact.created_by_id is None
        assert artefact.task_id is None

    # --- add_log ---

    def test_add_log_appends(self):
        report = self._report()
        first = self._add_log(report, "one")
        second = self._add_log(report, "two")

        assert first.id != second.id
        assert first.type == SignalReportArtefact.ArtefactType.NOTE  # derived from the content model
        notes = list(
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.NOTE).order_by(
                "created_at"
            )
        )
        assert [json.loads(n.content)["note"] for n in notes] == ["one", "two"]

    def test_add_log_rejects_status_content(self):
        report = self._report()
        with self.assertRaises(ValueError):
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(report.id),
                content=PriorityAssessment(priority=Priority.P1, explanation="x"),  # type: ignore[arg-type]
                attribution=ArtefactAttribution.system(),
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

    def test_append_status_rejects_log_content(self):
        report = self._report()
        with self.assertRaises(ValueError):
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(report.id),
                content=NoteArtefact(note="x"),  # type: ignore[arg-type]
                attribution=ArtefactAttribution.system(),
            )

    # --- append_finding ---

    def test_append_finding_appends_signal_finding(self):
        report = self._report()
        first = SignalReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=self._finding("s1"),
            attribution=ArtefactAttribution.system(),
        )
        second = SignalReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=str(report.id),
            content=self._finding("s2"),
            attribution=ArtefactAttribution.system(),
        )

        assert first.type == SignalReportArtefact.ArtefactType.SIGNAL_FINDING
        assert first.id != second.id
        assert (
            SignalReportArtefact.objects.filter(
                report=report, type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING
            ).count()
            == 2
        )

    # --- append_dismissal ---

    def test_append_dismissal_stacks_and_attributes(self):
        report = self._report()
        first = SignalReportArtefact.append_dismissal(
            team_id=self.team.id,
            report_id=str(report.id),
            content=Dismissal(reason="not_a_bug", user_id=self.user.id),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )
        second = SignalReportArtefact.append_dismissal(
            team_id=self.team.id,
            report_id=str(report.id),
            content=Dismissal(reason="wont_fix", note="later"),
            attribution=ArtefactAttribution.system(),
        )

        assert first.id != second.id
        assert first.created_by_id == self.user.id
        assert second.created_by_id is None
        assert (
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.DISMISSAL).count()
            == 2
        )

    # --- update_content ---

    def test_update_content_replaces_and_stamps_updated_at(self):
        report = self._report()
        artefact = self._add_log(report, "before")
        artefact.update_content(json.dumps({"note": "after"}))

        artefact.refresh_from_db()
        assert json.loads(artefact.content) == {"note": "after", "author": None}
        assert artefact.updated_at is not None

    def test_update_content_validates_against_row_type(self):
        report = self._report()
        artefact = self._add_log(report, "before")
        with self.assertRaises(ArtefactContentValidationError):
            artefact.update_content({"note": "   "})
