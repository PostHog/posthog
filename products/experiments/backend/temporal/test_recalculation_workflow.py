import uuid

import pytest
from unittest.mock import patch

import temporalio.worker
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.experiments.backend.temporal.models import (
    MAX_METRIC_ATTEMPTS,
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
        experiment_id: int,
        metric_uuid: str,
        recalculation_id: str,
        query_to: str,
        metric_type: str = "primary",
        is_final_attempt: bool = True,
    ) -> MetricRecalculationResult:
        calculate_calls.append((experiment_id, metric_uuid, recalculation_id, query_to, metric_type))
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
        # Two progress calls: start (mark_started) then finish (mark_completed). The XOR contract on the
        # progress activity forbids combining both into one call.
        assert len(progress_updates) == 2
        assert progress_updates[0].mark_started is True and progress_updates[0].mark_completed is False
        assert progress_updates[0].status == "in_progress"
        assert progress_updates[0].total_metrics == 0
        assert progress_updates[1].mark_completed is True and progress_updates[1].mark_started is False
        assert progress_updates[1].status == "completed"

    @parameterized.expand(
        [
            # name, failed_uuids, expected_result, expected_final_status
            # Any failure -> "failed" status; counts carry the partial-vs-total nuance.
            ("all_succeed", set(), {"total": 2, "succeeded": 2, "failed": 0}, "completed"),
            ("all_fail", {"m1", "m2"}, {"total": 2, "succeeded": 0, "failed": 2}, "failed"),
            ("partial_failure", {"m2"}, {"total": 2, "succeeded": 1, "failed": 1}, "failed"),
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

    async def test_transient_failure_is_requeued_and_retried_until_it_succeeds(self):
        # A raised activity is a transient failure: the workflow requeues the metric and retries it, freeing
        # the slot in between. m2 raises on its first two attempts, then succeeds on the third; m1 succeeds
        # immediately. The run ends fully succeeded, and m2 was invoked three times.
        metrics = [_metric("m1"), _metric("m2")]
        attempts: dict[str, int] = {}

        @activity.defn(name="discover_experiment_metrics")
        async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            return metrics

        @activity.defn(name="update_recalculation_progress")
        async def mock_update_progress(update: RecalculationProgressUpdate) -> str | None:
            return _START_QUERY_TO if update.mark_started else None

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            metric_type: str = "primary",
            is_final_attempt: bool = True,
        ) -> MetricRecalculationResult:
            attempts[metric_uuid] = attempts.get(metric_uuid, 0) + 1
            if metric_uuid == "m2" and attempts[metric_uuid] <= 2:
                raise RuntimeError("transient blip")
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        result = await _run_workflow([mock_discover, mock_update_progress, mock_calculate])

        assert result == {"total": 2, "succeeded": 2, "failed": 0}
        assert attempts["m1"] == 1
        assert attempts["m2"] == 3

    async def test_transient_failure_is_marked_failed_after_max_attempts(self):
        # A metric that raises on every attempt is requeued until MAX_METRIC_ATTEMPTS is exhausted, then
        # counted as failed (the final attempt persists the failure inside the real activity).
        metrics = [_metric("m1")]
        attempts: dict[str, int] = {}
        # is_final_attempt is the only signal that tells the real activity to persist the failure. Track it
        # per call so we can assert the workflow flips it to True exactly on the last attempt; otherwise a
        # run would be counted failed here while the metric row stayed in its loading state forever.
        is_final_attempt_log: list[bool] = []

        @activity.defn(name="discover_experiment_metrics")
        async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            return metrics

        @activity.defn(name="update_recalculation_progress")
        async def mock_update_progress(update: RecalculationProgressUpdate) -> str | None:
            return _START_QUERY_TO if update.mark_started else None

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            metric_type: str = "primary",
            is_final_attempt: bool = True,
        ) -> MetricRecalculationResult:
            attempts[metric_uuid] = attempts.get(metric_uuid, 0) + 1
            is_final_attempt_log.append(is_final_attempt)
            raise RuntimeError("always fails")

        result = await _run_workflow([mock_discover, mock_update_progress, mock_calculate])

        assert result == {"total": 1, "succeeded": 0, "failed": 1}
        assert attempts["m1"] == MAX_METRIC_ATTEMPTS
        # Only the final attempt is flagged final; earlier attempts must not be, or they'd persist early.
        assert is_final_attempt_log == [False] * (MAX_METRIC_ATTEMPTS - 1) + [True]

    @parameterized.expand(
        [
            # name, metrics — exercise both the empty-metrics path and the fan-out path.
            ("no_metrics", []),
            ("one_metric", [_metric("m1")]),
        ]
    )
    async def test_workflow_respects_progress_xor_contract(
        self, name: str, metrics: list[ExperimentMetricToRecalculate]
    ):
        # The production progress activity raises non-retryable ApplicationError when mark_started == mark_completed.
        # If the workflow ever combines both flags in one call (or sends neither), this test fails the run instead
        # of silently passing as the stub-mock path would.
        @activity.defn(name="discover_experiment_metrics")
        async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            return metrics

        @activity.defn(name="update_recalculation_progress")
        async def progress_with_xor_guard(update: RecalculationProgressUpdate) -> str | None:
            if update.mark_started == update.mark_completed:
                raise ApplicationError(
                    "RecalculationProgressUpdate must set exactly one of mark_started or mark_completed",
                    non_retryable=True,
                )
            return _START_QUERY_TO if update.mark_started else None

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            metric_type: str = "primary",
        ) -> MetricRecalculationResult:
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        # Workflow must complete without the validating activity raising — i.e., every progress call has exactly
        # one of mark_started / mark_completed set.
        await _run_workflow([mock_discover, progress_with_xor_guard, mock_calculate])

    @parameterized.expand(
        [
            # name, failed_uuids, metrics, expected_status — covers both return sites (empty and fan-out) and
            # both terminal status values. Without this, either return site could silently lose the counter
            # call without any test failure.
            ("empty_completes", set(), [], "completed"),
            ("all_succeed_completes", set(), [_metric("m1"), _metric("m2")], "completed"),
            ("any_failure_fails", {"m1"}, [_metric("m1"), _metric("m2")], "failed"),
        ]
    )
    async def test_workflow_finished_counter_fires_with_terminal_status(
        self, name: str, failed_uuids: set, metrics: list[ExperimentMetricToRecalculate], expected_status: str
    ):
        metric_results = {
            uuid_: MetricRecalculationResult(metric_uuid=uuid_, success=False, error_step="calculation")
            for uuid_ in failed_uuids
        }
        activities, _progress, _calls = _make_mock_activities(metrics=metrics, metric_results=metric_results)

        with patch(
            "products.experiments.backend.temporal.recalculation_workflow.increment_workflow_finished"
        ) as mock_finished:
            await _run_workflow(activities)

        mock_finished.assert_called_once_with(expected_status)

    async def test_workflow_fails_non_retryable_if_start_activity_returns_none(self):
        # The workflow narrows the start activity's Optional[str] return into a real str via an if/raise
        # (not assert, which python -O strips). If the activity ever violates its contract and returns None,
        # the workflow must fail non-retryably rather than silently pass None into calc activities.
        @activity.defn(name="discover_experiment_metrics")
        async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            return [_metric("m1")]

        @activity.defn(name="update_recalculation_progress")
        async def progress_returning_none(update: RecalculationProgressUpdate) -> str | None:
            return None  # contract violation on the start step

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            metric_type: str = "primary",
        ) -> MetricRecalculationResult:
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        with pytest.raises(WorkflowFailureError) as exc_info:
            await _run_workflow([mock_discover, progress_returning_none, mock_calculate])

        cause = exc_info.value.cause
        assert isinstance(cause, ApplicationError)
        assert cause.non_retryable is True
        assert "expected str" in str(cause)
