import json

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.task_run_artefacts import (
    TASK_RUN_TYPE_IMPLEMENTATION,
    TASK_RUN_TYPE_REPO_SELECTION,
    TASK_RUN_TYPE_RESEARCH,
    append_task_run_artefact,
)

# Task ORM model needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task  # tach-ignore


class TestBackfillTaskRunArtefacts(BaseTest):
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

    def _link(self, report: SignalReport, relationship: str) -> SignalReportTask:
        return SignalReportTask.objects.create(
            team=self.team,
            report=report,
            task=self._task(),
            relationship=relationship,
        )

    def _task_run_artefacts(self, report: SignalReport) -> list[SignalReportArtefact]:
        return list(SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN))

    def test_backfills_and_maps_relationships(self):
        report = self._report()
        research = self._link(report, TASK_RUN_TYPE_RESEARCH)
        implementation = self._link(report, TASK_RUN_TYPE_IMPLEMENTATION)
        repo_selection = self._link(report, TASK_RUN_TYPE_REPO_SELECTION)

        call_command("backfill_task_run_artefacts")

        artefacts = {json.loads(a.content)["task_id"]: json.loads(a.content) for a in self._task_run_artefacts(report)}
        assert all(c["product"] == "signals" for c in artefacts.values())
        assert artefacts[str(research.task_id)]["type"] == "research"
        assert artefacts[str(implementation.task_id)]["type"] == "implementation"
        assert artefacts[str(repo_selection.task_id)]["type"] == "repo_selection"

    def test_backdates_created_at_to_task_run(self):
        report = self._report()
        link = self._link(report, TASK_RUN_TYPE_RESEARCH)

        call_command("backfill_task_run_artefacts")

        artefact = self._task_run_artefacts(report)[0]
        assert artefact.created_at == link.created_at

    def test_is_idempotent(self):
        report = self._report()
        self._link(report, TASK_RUN_TYPE_RESEARCH)

        call_command("backfill_task_run_artefacts")
        call_command("backfill_task_run_artefacts")

        assert len(self._task_run_artefacts(report)) == 1

    def test_dry_run_writes_nothing(self):
        report = self._report()
        self._link(report, TASK_RUN_TYPE_RESEARCH)

        call_command("backfill_task_run_artefacts", "--dry-run")

        assert self._task_run_artefacts(report) == []

    def test_team_id_scopes_backfill(self):
        report = self._report()
        self._link(report, TASK_RUN_TYPE_RESEARCH)

        other_team_command_team_id = self.team.id + 99999
        call_command("backfill_task_run_artefacts", "--team-id", str(other_team_command_team_id))

        # Nothing for our team's report, since we scoped to a different (non-existent) team.
        assert self._task_run_artefacts(report) == []

    def test_unlabelled_rows_get_default_identifiers(self):
        # Artefacts are the sole source of association now, so unlabelled rows missing a
        # task_run artefact get one with the generic default identifiers.
        report = self._report()
        task = self._task()
        SignalReportTask.objects.create(team=self.team, report=report, task=task)

        call_command("backfill_task_run_artefacts")

        artefacts = self._task_run_artefacts(report)
        assert len(artefacts) == 1
        content = json.loads(artefacts[0].content)
        assert content["task_id"] == str(task.id)
        assert content["product"] == "tasks"
        assert content["type"] == "agent_run"

    def test_unlabelled_row_with_existing_artefact_is_skipped(self):
        report = self._report()
        task = self._task()
        SignalReportTask.objects.create(team=self.team, report=report, task=task)
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="tasks",
            type="agent_run",
            task_id=str(task.id),
        )

        call_command("backfill_task_run_artefacts")

        assert len(self._task_run_artefacts(report)) == 1

    def test_backfilled_artefacts_are_attributed_to_the_task(self):
        report = self._report()
        link = self._link(report, TASK_RUN_TYPE_RESEARCH)

        call_command("backfill_task_run_artefacts")

        artefact = self._task_run_artefacts(report)[0]
        assert str(artefact.task_id) == str(link.task_id)
