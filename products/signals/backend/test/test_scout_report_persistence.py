from contextlib import AbstractContextManager
from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope

from products.signals.backend.artefact_schemas import ActionabilityAssessment, ActionabilityChoice, SafetyJudgment
from products.signals.backend.models import (
    ArtefactAttribution,
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutRun,
)
from products.signals.backend.scout_harness.tools.emit import SOURCE_PRODUCT, SOURCE_TYPE
from products.signals.backend.scout_report import (
    InvalidScoutReportError,
    ScoutReportSignal,
    create_scout_report,
    soft_delete_scout_signal,
    update_scout_report,
)
from products.signals.backend.scout_report.judge import resolve_authored_report_status

PERSISTENCE_MODULE = "products.signals.backend.scout_report.persistence"


class TestScoutReportPersistence(BaseTest):
    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()
        cm = team_scope(self.team.id)
        cm.__enter__()
        self._team_scope_cm = cm
        patcher = patch(f"{PERSISTENCE_MODULE}.emit_embedding_request")
        self.emit_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            self._team_scope_cm.__exit__(None, None, None)
            self._team_scope_cm = None
        super().tearDown()

    def _make_run(self) -> SignalScoutRun:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=self.team,
            title="scout run",
            description="scout run",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        task_run = TaskRun.objects.create(task=task, team=self.team)
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-health-checks")
        run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=config,
            skill_name="signals-scout-health-checks",
            skill_version=1,
        )
        return run

    def test_create_writes_report_with_bound_signals_metadata(self) -> None:
        # The load-bearing contract (decision #5): each backing signal is written to the embeddings
        # pipeline with report_id pre-set, as a signals/signal row, so every read-side consumer
        # (source filter/chips, /signals/ tab, inbox-validation) resolves it like a pipeline signal.
        # Dropping report_id, or changing product/document_type, silently breaks all of them.
        run = self._make_run()
        task_id = str(run.task_run.task_id)
        result = create_scout_report(
            team_id=self.team.id,
            title="Checkout API p99 latency regressed",
            summary="The checkout endpoint p99 doubled after the 4.2 deploy.",
            signals=[
                ScoutReportSignal(description="p99 doubled on /checkout", source_id="obs-1", weight=1.0),
                ScoutReportSignal(description="error rate up 3x", source_id="obs-2", weight=0.5),
            ],
            attribution=ArtefactAttribution.from_task(task_id),
            run=run,
        )

        report = SignalReport.objects.get(id=result.report_id)
        assert report.status == SignalReport.Status.READY
        assert report.title == "Checkout API p99 latency regressed"
        # signal_count / total_weight must be real (not 0) — snooze re-promotion accounting reads them.
        assert report.signal_count == 2
        assert report.total_weight == 1.5

        assert self.emit_mock.call_count == 2
        first = self.emit_mock.call_args_list[0].kwargs
        assert first["product"] == "signals"
        assert first["document_type"] == "signal"
        assert first["rendering"] == "plain"
        assert first["metadata"]["report_id"] == result.report_id
        assert first["metadata"]["source_product"] == SOURCE_PRODUCT
        assert first["metadata"]["source_type"] == SOURCE_TYPE
        assert first["metadata"]["source_id"] == "obs-1"
        assert first["metadata"]["weight"] == 1.0
        assert "match_metadata" not in first["metadata"]  # never went through the matcher
        # Each backing row gets a distinct ClickHouse document_id.
        doc_ids = [call.kwargs["document_id"] for call in self.emit_mock.call_args_list]
        assert len(set(doc_ids)) == 2
        assert result.signal_document_ids == doc_ids

        # Provenance: a note artefact marks the report scout-authored and is attributed to the task.
        note = SignalReportArtefact.objects.get(report_id=result.report_id, type=SignalReportArtefact.ArtefactType.NOTE)
        assert str(note.task_id) == task_id

        run.refresh_from_db()
        assert run.emitted_report_ids == [result.report_id]

    @parameterized.expand(
        [
            ("empty_title", "", "summary", [ScoutReportSignal(description="d", source_id="s")]),
            ("empty_summary", "title", "  ", [ScoutReportSignal(description="d", source_id="s")]),
            ("no_signals", "title", "summary", []),
            ("blank_signal_description", "title", "summary", [ScoutReportSignal(description="  ", source_id="s")]),
        ]
    )
    def test_create_rejects_invalid_shape(self, _name, title, summary, signals) -> None:
        with pytest.raises(InvalidScoutReportError):
            create_scout_report(
                team_id=self.team.id,
                title=title,
                summary=summary,
                signals=signals,
                attribution=ArtefactAttribution.system(),
            )
        assert SignalReport.objects.filter(team_id=self.team.id).count() == 0
        self.emit_mock.assert_not_called()

    def test_update_rewrites_title_and_summary(self) -> None:
        result = create_scout_report(
            team_id=self.team.id,
            title="old title",
            summary="old summary",
            signals=[ScoutReportSignal(description="d", source_id="s")],
            attribution=ArtefactAttribution.system(),
        )
        updated = update_scout_report(
            team_id=self.team.id, report_id=result.report_id, title="new title", summary="new summary"
        )
        assert set(updated) == {"title", "summary", "updated_at"}
        report = SignalReport.objects.get(id=result.report_id)
        assert report.title == "new title"
        assert report.summary == "new summary"

    def test_update_fails_closed_on_cross_team_report(self) -> None:
        # edit_report can target any inbox report (decision #2) — so the team scope is the only thing
        # standing between a scout and another team's report. A cross-team id must raise, not no-op.
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        with team_scope(other_team.id):
            other_report = create_scout_report(
                team_id=other_team.id,
                title="theirs",
                summary="theirs",
                signals=[ScoutReportSignal(description="d", source_id="s")],
                attribution=ArtefactAttribution.system(),
            )
        with pytest.raises(InvalidScoutReportError):
            update_scout_report(team_id=self.team.id, report_id=other_report.report_id, title="hijacked")
        assert SignalReport.objects.get(id=other_report.report_id).title == "theirs"

    @parameterized.expand(
        [
            # Unsafe always suppresses, regardless of the scout's actionability call.
            ("unsafe_immediately", False, ActionabilityChoice.IMMEDIATELY_ACTIONABLE, SignalReport.Status.SUPPRESSED),
            ("unsafe_human", False, ActionabilityChoice.REQUIRES_HUMAN_INPUT, SignalReport.Status.SUPPRESSED),
            ("unsafe_not_actionable", False, ActionabilityChoice.NOT_ACTIONABLE, SignalReport.Status.SUPPRESSED),
            # Safe routes on actionability.
            ("safe_immediately", True, ActionabilityChoice.IMMEDIATELY_ACTIONABLE, SignalReport.Status.READY),
            ("safe_human", True, ActionabilityChoice.REQUIRES_HUMAN_INPUT, SignalReport.Status.PENDING_INPUT),
            ("safe_not_actionable", True, ActionabilityChoice.NOT_ACTIONABLE, SignalReport.Status.SUPPRESSED),
        ]
    )
    def test_resolve_authored_report_status(self, _name, safe, actionability, expected) -> None:
        assert resolve_authored_report_status(safe=safe, actionability=actionability) == expected

    def test_create_records_safety_and_actionability_artefacts(self) -> None:
        # The judge verdicts that set the status are persisted as the report's status artefacts, so the
        # inbox derives the same safety/actionability state a pipeline report would.
        result = create_scout_report(
            team_id=self.team.id,
            title="t",
            summary="s",
            signals=[ScoutReportSignal(description="d", source_id="obs")],
            attribution=ArtefactAttribution.system(),
            status=SignalReport.Status.PENDING_INPUT,
            safety=SafetyJudgment(choice=True, explanation=None),
            actionability=ActionabilityAssessment(
                explanation="needs a product decision",
                actionability=ActionabilityChoice.REQUIRES_HUMAN_INPUT,
                already_addressed=False,
            ),
        )
        report = SignalReport.objects.get(id=result.report_id)
        assert report.status == SignalReport.Status.PENDING_INPUT
        types = set(SignalReportArtefact.objects.filter(report_id=result.report_id).values_list("type", flat=True))
        assert SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT in types
        assert SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT in types

    def test_soft_delete_re_emits_tombstone_preserving_id_and_timestamp(self) -> None:
        # Soft-delete is a re-emit of the same document_id with metadata.deleted=True; the original
        # timestamp must be preserved so the tombstone lands in the same ReplacingMergeTree partition
        # and supersedes the live row rather than adding a sibling. The target report must be one the
        # team owns (team-scoped fail-closed), so author a real report first.
        report = create_scout_report(
            team_id=self.team.id,
            title="Checkout API p99 latency regressed",
            summary="The checkout endpoint p99 doubled after the 4.2 deploy.",
            signals=[ScoutReportSignal(description="p99 doubled on /checkout", source_id="obs-1", weight=1.0)],
            attribution=ArtefactAttribution.system(),
        )
        document_id = report.signal_document_ids[0]
        self.emit_mock.reset_mock()

        ts = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        soft_delete_scout_signal(
            team_id=self.team.id,
            report_id=report.report_id,
            document_id=document_id,
            description="p99 doubled on /checkout",
            timestamp=ts,
            source_id="obs-1",
        )
        kwargs = self.emit_mock.call_args.kwargs
        assert kwargs["document_id"] == document_id
        assert kwargs["timestamp"] == ts
        assert kwargs["metadata"]["deleted"] is True
        assert kwargs["metadata"]["report_id"] == report.report_id

    def test_create_rejects_duplicate_supplied_document_ids(self) -> None:
        # Two backing signals sharing a document_id would collapse in the ReplacingMergeTree, leaving
        # the report claiming more evidence than reads can resolve — reject at validation time.
        with pytest.raises(InvalidScoutReportError):
            create_scout_report(
                team_id=self.team.id,
                title="t",
                summary="s",
                signals=[
                    ScoutReportSignal(description="a", source_id="obs-1", document_id="dup"),
                    ScoutReportSignal(description="b", source_id="obs-2", document_id="dup"),
                ],
                attribution=ArtefactAttribution.system(),
            )

    def test_soft_delete_rejects_report_another_team_owns(self) -> None:
        # Fail-closed: a report_id the team doesn't own must raise before any tombstone is emitted,
        # so a foreign report_id + known document_id can't soft-delete another tenant's signal.
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"), name="other")
        with team_scope(other_team.id):
            foreign = create_scout_report(
                team_id=other_team.id,
                title="Other team report",
                summary="Belongs to a different tenant.",
                signals=[ScoutReportSignal(description="obs", source_id="obs-x", weight=1.0)],
                attribution=ArtefactAttribution.system(),
            )
        self.emit_mock.reset_mock()
        with pytest.raises(InvalidScoutReportError):
            soft_delete_scout_signal(
                team_id=self.team.id,
                report_id=foreign.report_id,
                document_id=foreign.signal_document_ids[0],
                description="obs",
                timestamp=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                source_id="obs-x",
            )
        self.emit_mock.assert_not_called()
