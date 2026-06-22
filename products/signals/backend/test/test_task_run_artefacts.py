import json

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.signals.backend.custom_agent.persistence import create_custom_agent_ready_report
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.task_run_artefacts import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
    TASK_RUN_TYPE_REPO_SELECTION,
    TASK_RUN_TYPE_RESEARCH,
    aappend_task_run_artefact,
    append_task_run_artefact,
    record_implementation_task,
    signals_task_ids,
)
from products.tasks.backend.logic.repo_selection.types import RepoSelectionResult
from products.tasks.backend.models import Task


class TestTaskRunArtefacts(BaseTest):
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

    def _task_run_artefacts(self, report: SignalReport) -> list[SignalReportArtefact]:
        return list(SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN))

    @parameterized.expand(
        [
            (TASK_RUN_TYPE_RESEARCH,),
            (TASK_RUN_TYPE_IMPLEMENTATION,),
            (TASK_RUN_TYPE_REPO_SELECTION,),
        ]
    )
    def test_append_records_signals_product_and_type(self, task_type):
        report = self._report()
        task = self._task()

        artefact = append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=task_type,
            task_id=str(task.id),
        )

        content = json.loads(artefact.content)
        assert artefact.type == SignalReportArtefact.ArtefactType.TASK_RUN
        assert content["task_id"] == str(task.id)
        assert content["product"] == "signals"
        assert content["type"] == task_type
        assert content["run_id"] is None

    def test_append_attributes_artefact_to_the_task(self):
        report = self._report()
        task = self._task()

        artefact = append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_RESEARCH,
            task_id=str(task.id),
        )

        assert str(artefact.task_id) == str(task.id)
        assert artefact.created_by_id is None

    async def test_aappend_carries_run_id(self):
        report = await SignalReport.objects.acreate(
            team=self.team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )
        task = await Task.objects.acreate(
            team=self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

        artefact = await aappend_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_IMPLEMENTATION,
            task_id=str(task.id),
            run_id="run-789",
        )

        content = json.loads(artefact.content)
        assert content["task_id"] == str(task.id)
        assert content["run_id"] == "run-789"
        assert content["product"] == "signals"
        assert content["type"] == "implementation"

    def test_signals_task_ids_filters_by_product_and_type(self):
        report = self._report()
        task = self._task()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_RESEARCH,
            task_id=str(task.id),
        )
        other_task = self._task()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="billing",
            type=TASK_RUN_TYPE_IMPLEMENTATION,
            task_id=str(other_task.id),
        )

        assert signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_RESEARCH) == [str(task.id)]
        # The custom product's "implementation" row doesn't count as a signals implementation.
        assert signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_IMPLEMENTATION) == []

    def test_record_implementation_task_writes_gate_row_and_artefact(self):
        report = self._report()
        task = self._task()
        record_implementation_task(team_id=self.team.id, report_id=str(report.id), task_id=str(task.id))

        # Both the legacy SignalReportTask gate row and the task_run work-log artefact are written.
        assert SignalReportTask.objects.filter(
            report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        ).exists()
        assert signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_IMPLEMENTATION) == [str(task.id)]

        # Idempotent on the gate row for the same task — re-recording doesn't duplicate the link.
        record_implementation_task(team_id=self.team.id, report_id=str(report.id), task_id=str(task.id))
        assert SignalReportTask.objects.filter(report=report, task=task).count() == 1

    def _final_report(self) -> CustomAgentFinalReport:
        return CustomAgentFinalReport(
            title="title",
            description="description",
            actionability=ActionabilityAssessment(
                explanation="e",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            assignees=[],
            priority=PriorityAssessment(explanation="e", priority=Priority.P1),
        )

    def test_custom_agent_report_with_task_uses_agent_identifier(self):
        task = self._task()

        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=RepoSelectionResult(repository="acme/repo", reason="r"),
            task_id=str(task.id),
            agent_identifier=("billing", "anomaly_scan"),
        )

        report = SignalReport.objects.get(id=persisted.report_id)
        artefacts = self._task_run_artefacts(report)
        assert len(artefacts) == 1
        content = json.loads(artefacts[0].content)
        assert content["task_id"] == str(task.id)
        assert content["product"] == "billing"
        assert content["type"] == "anomaly_scan"
        # Everything the custom agent produced is attributed to its task.
        for artefact in SignalReportArtefact.objects.filter(report=report):
            assert str(artefact.task_id) == str(task.id)

    def test_custom_agent_report_without_task_appends_nothing(self):
        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=RepoSelectionResult(repository="acme/repo", reason="r"),
            task_id=None,
            agent_identifier=("billing", "anomaly_scan"),
        )

        report = SignalReport.objects.get(id=persisted.report_id)
        assert self._task_run_artefacts(report) == []
        # No task in scope — system attribution (both columns null).
        for artefact in SignalReportArtefact.objects.filter(report=report):
            assert artefact.task_id is None
            assert artefact.created_by_id is None
