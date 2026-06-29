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
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult

# Task/TaskRun ORM models needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task, TaskRun  # tach-ignore


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


class TestAssociatedTaskRunsFilter(BaseTest):
    """`SignalReport.associated_task_runs_filter` matches a TaskRun whose task is associated with
    the report via either source (task_run artefact or legacy SignalReportTask)."""

    def _report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )

    def _task_with_run(self) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team, title="task", description="desc", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )
        return task, TaskRun.objects.create(team=self.team, task=task, status=TaskRun.Status.COMPLETED)

    def _matched_task_ids(self, report: SignalReport) -> set[str]:
        return {
            str(task_id)
            for task_id in TaskRun.objects.filter(SignalReport.associated_task_runs_filter(report.id)).values_list(
                "task_id", flat=True
            )
        }

    def test_matches_task_associated_via_artefact_only(self):
        report = self._report()
        task, _run = self._task_with_run()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_IMPLEMENTATION,
            task_id=str(task.id),
        )
        assert not SignalReportTask.objects.filter(report=report).exists()
        assert self._matched_task_ids(report) == {str(task.id)}

    def test_matches_task_associated_via_signal_report_task_only(self):
        report = self._report()
        task, _run = self._task_with_run()
        SignalReportTask.objects.create(
            team=self.team, report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        )
        assert not SignalReportArtefact.objects.filter(report=report).exists()
        assert self._matched_task_ids(report) == {str(task.id)}

    def test_unions_both_sources_without_duplicate_rows(self):
        report = self._report()
        task, _run = self._task_with_run()
        # Dual-writes both the gate row and the artefact for the same task.
        record_implementation_task(team_id=self.team.id, report_id=str(report.id), task_id=str(task.id))
        # OR of two task_id__in subqueries must not double-count the run.
        assert TaskRun.objects.filter(SignalReport.associated_task_runs_filter(report.id)).count() == 1
        assert self._matched_task_ids(report) == {str(task.id)}

    def test_excludes_tasks_associated_with_a_different_report(self):
        report = self._report()
        other_report = self._report()
        other_task, _run = self._task_with_run()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(other_report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_IMPLEMENTATION,
            task_id=str(other_task.id),
        )
        assert self._matched_task_ids(report) == set()
        assert self._matched_task_ids(other_report) == {str(other_task.id)}


class TestReportsForTaskFilter(BaseTest):
    """`SignalReport.reports_for_task_filter` matches the reports a task is associated with via
    either source (task_run artefact or legacy SignalReportTask)."""

    def _report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=1, total_weight=1.0
        )

    def _task(self) -> Task:
        return Task.objects.create(
            team=self.team, title="task", description="desc", origin_product=Task.OriginProduct.SIGNAL_REPORT
        )

    def _matched_report_ids(self, task: Task) -> set[str]:
        return {
            str(report_id)
            for report_id in SignalReport.objects.filter(SignalReport.reports_for_task_filter(task.id)).values_list(
                "id", flat=True
            )
        }

    def test_matches_report_associated_via_artefact_only(self):
        report = self._report()
        task = self._task()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_IMPLEMENTATION,
            task_id=str(task.id),
        )
        assert not SignalReportTask.objects.filter(task=task).exists()
        assert self._matched_report_ids(task) == {str(report.id)}

    def test_matches_report_associated_via_signal_report_task_only(self):
        report = self._report()
        task = self._task()
        SignalReportTask.objects.create(
            team=self.team, report=report, task=task, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        )
        assert not SignalReportArtefact.objects.filter(task=task).exists()
        assert self._matched_report_ids(task) == {str(report.id)}

    def test_unions_both_sources_without_duplicate_rows(self):
        report = self._report()
        task = self._task()
        record_implementation_task(team_id=self.team.id, report_id=str(report.id), task_id=str(task.id))
        assert SignalReport.objects.filter(SignalReport.reports_for_task_filter(task.id)).count() == 1
        assert self._matched_report_ids(task) == {str(report.id)}

    def test_excludes_reports_not_associated_with_the_task(self):
        report = self._report()
        task = self._task()
        other_task = self._task()
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product=SIGNALS_PRODUCT,
            type=TASK_RUN_TYPE_IMPLEMENTATION,
            task_id=str(task.id),
        )
        assert self._matched_report_ids(other_task) == set()
        assert self._matched_report_ids(task) == {str(report.id)}
