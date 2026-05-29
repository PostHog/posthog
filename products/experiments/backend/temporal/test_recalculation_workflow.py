import uuid

import pytest

import temporalio.worker
from parameterized import parameterized
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.experiments.backend.temporal.models import (
    ExperimentMetricsRecalculationWorkflowInputs,
    ExperimentMetricToRecalculate,
    MetricRecalculationResult,
    RecalculationProgressUpdate,
)
from products.experiments.backend.temporal.recalculation_workflow import ExperimentMetricsRecalculationWorkflow

_START_QUERY_TO = "2026-05-29T12:00:00+00:00"


def _metric(metric_uuid: str) -> ExperimentMetricToRecalculate:
    return ExperimentMetricToRecalculate(experiment_id=1, metric_uuid=metric_uuid, metric_type="primary")


def _make_mock_activities(
    metrics: list[ExperimentMetricToRecalculate] | None = None,
    metric_results: dict[str, MetricRecalculationResult] | None = None,
):
    metrics = metrics or []
    metric_results = metric_results or {}
    progress_updates: list[RecalculationProgressUpdate] = []
    calculate_calls: list[tuple] = []

    @activity.defn(name="discover_experiment_metrics")
    async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
        return metrics

    @activity.defn(name="update_recalculation_progress")
    async def mock_update_progress(update: RecalculationProgressUpdate) -> str | None:
        progress_updates.append(update)
        # Mirror the real activity (option A): return the run's shared query_to on the start step.
        return _START_QUERY_TO if update.mark_started else None

    @activity.defn(name="calculate_experiment_metric_for_recalculation")
    async def mock_calculate(
        experiment_id: int, metric_uuid: str, recalculation_id: str, query_to: str
    ) -> MetricRecalculationResult:
        calculate_calls.append((experiment_id, metric_uuid, recalculation_id, query_to))
        return metric_results.get(metric_uuid, MetricRecalculationResult(metric_uuid=metric_uuid, success=True))

    activities = [mock_discover, mock_update_progress, mock_calculate]
    return activities, progress_updates, calculate_calls


async def _run_workflow(activities) -> dict:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ExperimentMetricsRecalculationWorkflow],
            activities=activities,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                ExperimentMetricsRecalculationWorkflow.run,
                ExperimentMetricsRecalculationWorkflowInputs(recalculation_id=str(uuid.uuid4())),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
class TestExperimentMetricsRecalculationWorkflow:
    async def test_no_metrics_completes_immediately(self):
        activities, progress_updates, calculate_calls = _make_mock_activities(metrics=[])

        result = await _run_workflow(activities)

        assert result == {"total": 0, "succeeded": 0, "failed": 0}
        assert calculate_calls == []
        # Single progress call that both starts and completes the (empty) run.
        assert len(progress_updates) == 1
        assert progress_updates[0].mark_started is True
        assert progress_updates[0].mark_completed is True
        assert progress_updates[0].status == "completed"

    @parameterized.expand(
        [
            # name, failed_uuids, expected_result, expected_final_status
            ("all_succeed", set(), {"total": 2, "succeeded": 2, "failed": 0}, "completed"),
            ("all_fail", {"m1", "m2"}, {"total": 2, "succeeded": 0, "failed": 2}, "failed"),
            ("partial_failure", {"m2"}, {"total": 2, "succeeded": 1, "failed": 1}, "completed"),
        ]
    )
    async def test_outcomes(self, name: str, failed_uuids: set, expected_result: dict, expected_final_status: str):
        metrics = [_metric("m1"), _metric("m2")]
        metric_results = {
            uuid_: MetricRecalculationResult(metric_uuid=uuid_, success=False, error_step="calculation")
            for uuid_ in failed_uuids
        }
        activities, progress_updates, calculate_calls = _make_mock_activities(
            metrics=metrics, metric_results=metric_results
        )

        result = await _run_workflow(activities)

        assert result == expected_result
        assert {c[1] for c in calculate_calls} == {"m1", "m2"}
        # The shared query_to from the start step is threaded into every calc activity.
        assert {c[3] for c in calculate_calls} == {_START_QUERY_TO}
        assert progress_updates[-1].status == expected_final_status
        assert progress_updates[-1].mark_completed is True
