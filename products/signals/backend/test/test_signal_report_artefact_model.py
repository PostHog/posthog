import json

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError,
    Dismissal,
    NoteArtefact,
    Priority,
    PriorityAssessment,
    RelatedTo,
    ReportLink,
    SignalFinding,
)
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.temporal.agentic.report import _AGENTIC_ARTEFACT_TYPES

# Task ORM model needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task


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

    @parameterized.expand([("add_log",), ("append",)])
    def test_related_to_writes_symmetric_backlink(self, write_method):
        # A related_to link must be maintained on both reports from either write entry point, and
        # must not recurse (exactly one row per side).
        report_a = self._report()
        report_b = self._report()
        writer = getattr(SignalReportArtefact, write_method)
        writer(
            team_id=self.team.id,
            report_id=str(report_a.id),
            content=RelatedTo(report_id=str(report_b.id)),
            attribution=ArtefactAttribution.system(),
        )

        def links_of(report: SignalReport) -> list[str]:
            return [
                RelatedTo.model_validate_json(a.content).report_id
                for a in SignalReportArtefact.objects.filter(
                    report=report, type=SignalReportArtefact.ArtefactType.RELATED_TO
                )
            ]

        assert links_of(report_a) == [str(report_b.id)]
        assert links_of(report_b) == [str(report_a.id)]

    # --- report_link ---

    def _link(
        self,
        source: SignalReport,
        target: SignalReport,
        kind: ReportLinkKind = ReportLinkKind.DEPENDS_ON,
        *,
        team_id: int | None = None,
    ) -> SignalReportArtefact:
        return SignalReportArtefact.add_log(
            team_id=self.team.id if team_id is None else team_id,
            report_id=str(source.id),
            content=ReportLink(kind=kind, report_id=str(target.id)),
            attribution=ArtefactAttribution.system(),
        )

    def _links_of(self, report: SignalReport) -> list[tuple[str, str]]:
        return [
            (link.kind.value, link.report_id)
            for link in (
                ReportLink.model_validate_json(a.content)
                for a in SignalReportArtefact.objects.filter(
                    report=report, type=SignalReportArtefact.ArtefactType.REPORT_LINK
                ).order_by("created_at")
            )
        ]

    @parameterized.expand([("add_log",), ("append",)])
    def test_report_link_is_directed_and_writes_no_backlink(self, write_method):
        # The direction is the payload, so unlike related_to the target must stay untouched from
        # either write entry point. A mirror row would assert the opposite relationship.
        report_a = self._report()
        report_b = self._report()
        getattr(SignalReportArtefact, write_method)(
            team_id=self.team.id,
            report_id=str(report_a.id),
            content=ReportLink(kind=ReportLinkKind.DEPENDS_ON, report_id=str(report_b.id), reason="stacked"),
            attribution=ArtefactAttribution.system(),
        )

        assert self._links_of(report_a) == [("depends_on", str(report_b.id))]
        assert self._links_of(report_b) == []

    def test_report_link_rejects_self_link(self):
        report = self._report()
        with self.assertRaises(ArtefactContentValidationError):
            self._link(report, report)

    def test_report_link_rejects_a_report_in_another_team(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        foreign = SignalReport.objects.create(
            team=other_team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        with self.assertRaises(ArtefactContentValidationError):
            self._link(self._report(), foreign)

    def test_report_link_rejects_a_source_report_in_another_team(self):
        # The write locks the source report row before the team's link lock, so a report_id the
        # team does not own has to fail there rather than insert an artefact against it.
        other_team = Team.objects.create(organization=self.organization, name="other source")
        foreign_source = SignalReport.objects.create(
            team=other_team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        with self.assertRaises(ArtefactContentValidationError):
            self._link(foreign_source, self._report())

    def test_report_link_rejects_a_deleted_report(self):
        target = self._report()
        target.status = SignalReport.Status.DELETED
        target.save(update_fields=["status"])
        with self.assertRaises(ArtefactContentValidationError):
            self._link(self._report(), target)

    @parameterized.expand([(2,), (3,)])
    def test_report_link_rejects_a_cycle_of_one_kind(self, chain_length):
        # A -> B -> ... -> A must be refused at the closing link, so a dependency chain always has
        # a first report and the pipeline can order the stack.
        chain = [self._report() for _ in range(chain_length)]
        for source, target in zip(chain, chain[1:]):
            self._link(source, target)

        with self.assertRaises(ArtefactContentValidationError):
            self._link(chain[-1], chain[0])

    def test_report_link_allows_different_kinds_between_the_same_pair(self):
        # Kinds are separate claims, so the cycle check must not treat a link of one kind as an
        # edge of another. "A depends_on B" and "B follow_up_of A" are both true of a stack.
        report_a = self._report()
        report_b = self._report()
        self._link(report_a, report_b, ReportLinkKind.DEPENDS_ON)
        self._link(report_b, report_a, ReportLinkKind.FOLLOW_UP_OF)

        assert self._links_of(report_a) == [("depends_on", str(report_b.id))]
        assert self._links_of(report_b) == [("follow_up_of", str(report_a.id))]

    def test_editing_a_report_link_cannot_install_a_rejected_link(self):
        # update_content is a second way to write a link, so it answers to the same invariants.
        # Otherwise a PATCH is the way around them.
        report_a = self._report()
        report_b = self._report()
        report_c = self._report()
        self._link(report_b, report_a)
        link = self._link(report_a, report_c)

        with self.assertRaises(ArtefactContentValidationError):
            link.update_content({"kind": "depends_on", "report_id": str(report_b.id)})
        with self.assertRaises(ArtefactContentValidationError):
            link.update_content({"kind": "depends_on", "report_id": str(report_a.id)})
        assert self._links_of(report_a) == [("depends_on", str(report_c.id))]

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
