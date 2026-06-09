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
    aappend_task_run_artefact,
    append_task_run_artefact,
)
from products.tasks.backend.models import Task
from products.tasks.backend.repo_selection.agent import RepoSelectionResult


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

    def _task_run_artefacts(self, report: SignalReport) -> list[SignalReportArtefact]:
        return list(SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.TASK_RUN))

    @parameterized.expand(
        [
            (SignalReportTask.Relationship.RESEARCH, "research"),
            (SignalReportTask.Relationship.IMPLEMENTATION, "implementation"),
            (SignalReportTask.Relationship.REPO_SELECTION, "repo_selection"),
        ]
    )
    def test_append_records_signals_product_and_type(self, relationship, expected_type):
        report = self._report()

        artefact = append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=relationship,
            task_id="task-123",
        )

        content = json.loads(artefact.content)
        assert artefact.type == SignalReportArtefact.ArtefactType.TASK_RUN
        assert content["task_id"] == "task-123"
        assert content["product"] == "signals"
        assert content["type"] == expected_type
        assert content["run_id"] is None

    async def test_aappend_carries_run_id(self):
        report = await SignalReport.objects.acreate(
            team=self.team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            signal_count=1,
            total_weight=1.0,
        )

        artefact = await aappend_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=SignalReportTask.Relationship.IMPLEMENTATION,
            task_id="task-456",
            run_id="run-789",
        )

        content = json.loads(artefact.content)
        assert content["task_id"] == "task-456"
        assert content["run_id"] == "run-789"
        assert content["product"] == "signals"
        assert content["type"] == "implementation"

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
        task = Task.objects.create(
            team=self.team,
            title="task",
            description="desc",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

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
