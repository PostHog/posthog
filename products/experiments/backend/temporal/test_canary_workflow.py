import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.experiments.backend.temporal.canary_workflow import ExperimentPrecomputeCanaryWorkflow
from products.experiments.backend.temporal.models import (
    OUTCOME_ERROR,
    OUTCOME_PASS,
    OUTCOME_SKIPPED,
    CanaryMetricResult,
    CanaryMetricTarget,
    CanaryReportInputs,
    ExperimentPrecomputeCanaryInputs,
)


def _target(metric_uuid: str, experiment_id: int = 1) -> CanaryMetricTarget:
    return CanaryMetricTarget(team_id=1, experiment_id=experiment_id, metric_uuid=metric_uuid, metric_type="funnel")


def _make_mock_activities(targets: list[CanaryMetricTarget], failing_uuids: set[str] | None = None):
    failing_uuids = failing_uuids or set()
    run_calls: list[CanaryMetricTarget] = []
    reports: list[CanaryReportInputs] = []

    @activity.defn(name="sample_experiment_canary_targets")
    async def mock_sample(inputs: ExperimentPrecomputeCanaryInputs) -> list[CanaryMetricTarget]:
        return targets

    @activity.defn(name="run_experiment_metric_canary")
    async def mock_run(target: CanaryMetricTarget) -> CanaryMetricResult:
        run_calls.append(target)
        if target.metric_uuid in failing_uuids:
            raise ApplicationError("clickhouse timeout", non_retryable=True)
        return CanaryMetricResult(target=target, outcome=OUTCOME_PASS)

    @activity.defn(name="report_experiment_canary_results")
    async def mock_report(report: CanaryReportInputs) -> None:
        reports.append(report)

    return [mock_sample, mock_run, mock_report], run_calls, reports


async def _run_workflow(activities, inputs: ExperimentPrecomputeCanaryInputs) -> dict:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ExperimentPrecomputeCanaryWorkflow],
            activities=activities,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                ExperimentPrecomputeCanaryWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
class TestExperimentPrecomputeCanaryWorkflow:
    async def test_runs_each_target_and_reports(self):
        targets = [_target("m1"), _target("m2"), _target("m3", experiment_id=2)]
        activities, run_calls, reports = _make_mock_activities(targets)

        result = await _run_workflow(activities, ExperimentPrecomputeCanaryInputs())

        assert result == {"total": 3, OUTCOME_PASS: 3}
        assert [t.metric_uuid for t in run_calls] == ["m1", "m2", "m3"]
        assert len(reports) == 1
        assert [r.outcome for r in reports[0].results] == [OUTCOME_PASS] * 3
        assert reports[0].triggered_manually is False

    async def test_failed_activity_becomes_error_outcome_and_loop_continues(self):
        targets = [_target("m1"), _target("m2"), _target("m3")]
        activities, run_calls, reports = _make_mock_activities(targets, failing_uuids={"m2"})

        result = await _run_workflow(activities, ExperimentPrecomputeCanaryInputs())

        assert result == {"total": 3, OUTCOME_PASS: 2, OUTCOME_ERROR: 1}
        assert [t.metric_uuid for t in run_calls] == ["m1", "m2", "m3"]
        outcomes = {r.target.metric_uuid: r.outcome for r in reports[0].results}
        assert outcomes == {"m1": OUTCOME_PASS, "m2": OUTCOME_ERROR, "m3": OUTCOME_PASS}

    async def test_exhausted_time_budget_skips_remaining_metrics(self):
        targets = [_target("m1"), _target("m2")]
        activities, run_calls, reports = _make_mock_activities(targets)

        result = await _run_workflow(activities, ExperimentPrecomputeCanaryInputs(time_budget_seconds=-1))

        assert result == {"total": 2, OUTCOME_SKIPPED: 2}
        assert run_calls == []
        assert all(r.detail == "time budget exhausted" for r in reports[0].results)

    async def test_no_targets_still_reports(self):
        activities, run_calls, reports = _make_mock_activities([])

        result = await _run_workflow(activities, ExperimentPrecomputeCanaryInputs(triggered_manually=True))

        assert result == {"total": 0}
        assert run_calls == []
        assert len(reports) == 1
        assert reports[0].results == []
        assert reports[0].triggered_manually is True
