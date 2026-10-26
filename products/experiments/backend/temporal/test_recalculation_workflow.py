import uuid
import asyncio
from collections.abc import Callable
from contextlib import ExitStack
from datetime import timedelta

import pytest
from unittest.mock import patch

import temporalio.worker
import temporalio.workflow
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHistory
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.dataclasses import frozen

from products.experiments.backend.recalculation import _STALE_RECALC_THRESHOLD
from products.experiments.backend.temporal.models import (
    MAX_METRIC_ATTEMPTS,
    METRIC_CALC_HEARTBEAT_TIMEOUT_SECONDS,
    METRIC_CALC_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS,
    METRIC_FAILURE_BACKSTOP_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS,
    RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS,
    RECALCULATION_PROGRESS_MAX_ATTEMPTS,
    ExperimentMetricsRecalculationWorkflowInputs,
    ExperimentMetricToRecalculate,
    MetricOutOfTimeFailure,
    MetricRecalculationResult,
    RecalculationProgressUpdate,
)
from products.experiments.backend.temporal.recalculation_activities import calculate_experiment_metric_for_recalculation
from products.experiments.backend.temporal.recalculation_workflow import ExperimentMetricsRecalculationWorkflow

_START_QUERY_TO = "2026-05-29T12:00:00+00:00"
_WORKFLOW_MODULE = "products.experiments.backend.temporal.recalculation_workflow"
_ACTIVITIES_MODULE = "products.experiments.backend.temporal.recalculation_activities"


def _metric(metric_uuid: str) -> ExperimentMetricToRecalculate:
    return ExperimentMetricToRecalculate(experiment_id=1, metric_uuid=metric_uuid, role="primary")


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
        role: str = "primary",
    ) -> MetricRecalculationResult:
        calculate_calls.append((experiment_id, metric_uuid, recalculation_id, query_to, role))
        return metric_results.get(metric_uuid, MetricRecalculationResult(metric_uuid=metric_uuid, success=True))

    activities = [mock_discover, mock_update_progress, mock_calculate]
    return activities, progress_updates, calculate_calls


def _mock_out_of_time_backstop() -> tuple[Callable, list[MetricOutOfTimeFailure]]:
    recorded: list[MetricOutOfTimeFailure] = []

    @activity.defn(name="record_metric_out_of_time_failure")
    async def mock_backstop(failure: MetricOutOfTimeFailure) -> None:
        recorded.append(failure)

    return mock_backstop, recorded


def _worst_case_seconds(timeout_seconds: float, max_attempts: int) -> float:
    # Temporal's default RetryPolicy waits 1 s before the first retry and doubles the wait after each one.
    return timeout_seconds * max_attempts + sum(2**retry for retry in range(max_attempts - 1))


def test_in_progress_phase_ends_before_the_staleness_ttl():
    worst_case = (
        METRIC_CALC_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS
        + METRIC_FAILURE_BACKSTOP_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS
        + _worst_case_seconds(RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS, RECALCULATION_PROGRESS_MAX_ATTEMPTS)
    )

    assert worst_case < _STALE_RECALC_THRESHOLD.total_seconds()


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


def _recording_calculate(calls: list[str]) -> Callable:
    @activity.defn(name="calculate_experiment_metric_for_recalculation")
    async def mock_calculate(
        experiment_id: int,
        metric_uuid: str,
        recalculation_id: str,
        query_to: str,
        role: str = "primary",
    ) -> MetricRecalculationResult:
        calls.append(metric_uuid)
        return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

    return mock_calculate


@frozen
class _TwoQueueRun:
    result: dict
    workflow_queue_calls: list[str]
    activity_queue_calls: list[str]
    history: WorkflowHistory


async def _run_with_activity_queue_worker(
    activity_task_queue: str | None, activity_worker_task_queue: str
) -> _TwoQueueRun:
    activities, _progress, _calls = _make_mock_activities(metrics=[_metric("m1")])
    workflow_queue_calls: list[str] = []
    activity_queue_calls: list[str] = []
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with (
            Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ExperimentMetricsRecalculationWorkflow],
                activities=[*activities[:2], _recording_calculate(workflow_queue_calls)],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ),
            Worker(
                env.client,
                task_queue=activity_worker_task_queue,
                activities=[_recording_calculate(activity_queue_calls)],
            ),
        ):
            handle = await env.client.start_workflow(
                ExperimentMetricsRecalculationWorkflow.run,
                ExperimentMetricsRecalculationWorkflowInputs(
                    recalculation_id=str(uuid.uuid4()), activity_task_queue=activity_task_queue
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            result = await handle.result()
            history = await handle.fetch_history()
    return _TwoQueueRun(
        result=result,
        workflow_queue_calls=workflow_queue_calls,
        activity_queue_calls=activity_queue_calls,
        history=history,
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

    async def test_transient_failure_is_retried_until_it_succeeds(self):
        # A raised activity is a transient failure: Temporal's retry policy re-dispatches it. m2 raises on
        # its first two attempts, then succeeds on the third; m1 succeeds immediately. The run ends fully
        # succeeded, and m2 was invoked three times.
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
            role: str = "primary",
        ) -> MetricRecalculationResult:
            attempts[metric_uuid] = attempts.get(metric_uuid, 0) + 1
            if metric_uuid == "m2" and attempts[metric_uuid] <= 2:
                raise RuntimeError("transient blip")
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        result = await _run_workflow([mock_discover, mock_update_progress, mock_calculate])

        assert result == {"total": 2, "succeeded": 2, "failed": 0}
        assert attempts["m1"] == 1
        assert attempts["m2"] == 3

    async def test_exhausted_retries_mark_failed_and_finality_derives_from_attempt_count(self):
        # A metric that raises on every attempt is retried by the activity retry policy until
        # MAX_METRIC_ATTEMPTS is exhausted, then counted as failed. Runs the REAL activity wrapper (with the
        # DB-touching sync implementation patched out) because the wrapper derives is_final_attempt from
        # activity.info().attempt against the same constant the retry policy is built from — if those two
        # sides drift, the FAILED row never persists and the metric row stays in its loading state forever.
        recorded_flags: list[bool] = []

        @activity.defn(name="discover_experiment_metrics")
        async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            return [_metric("m1")]

        @activity.defn(name="update_recalculation_progress")
        async def mock_update_progress(update: RecalculationProgressUpdate) -> str | None:
            return _START_QUERY_TO if update.mark_started else None

        async def failing_sync(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            role: str,
            is_final_attempt: bool,
            attempt: int,
        ) -> MetricRecalculationResult:
            recorded_flags.append(is_final_attempt)
            raise RuntimeError("always fails")

        mock_backstop, backstop_calls = _mock_out_of_time_backstop()

        with patch(
            "products.experiments.backend.temporal.recalculation_activities._calculate_experiment_metric_for_recalculation_sync",
            new=failing_sync,
        ):
            result = await _run_workflow(
                [mock_discover, mock_update_progress, calculate_experiment_metric_for_recalculation, mock_backstop]
            )

        assert result == {"total": 1, "succeeded": 0, "failed": 1}
        # Only the final attempt is flagged final; earlier attempts must not be, or they'd persist early.
        assert recorded_flags == [False] * (MAX_METRIC_ATTEMPTS - 1) + [True]
        # The final attempt persisted the failure itself, so the backstop has nothing to do.
        assert backstop_calls == []

    async def test_calc_activity_has_a_total_budget_and_a_heartbeat_timeout(self):
        activities, _progress, _calls = _make_mock_activities(metrics=[_metric("m1")])
        timeouts: list[tuple[timedelta | None, timedelta | None]] = []

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            role: str = "primary",
        ) -> MetricRecalculationResult:
            info = activity.info()
            timeouts.append((info.schedule_to_close_timeout, info.heartbeat_timeout))
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        await _run_workflow([*activities[:2], mock_calculate])

        assert timeouts == [
            (
                timedelta(seconds=METRIC_CALC_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS),
                timedelta(seconds=METRIC_CALC_HEARTBEAT_TIMEOUT_SECONDS),
            )
        ]

    @parameterized.expand(
        [
            # Retryable errors until the total budget leaves no room for the next attempt.
            ("budget_ends_the_retries", False, {"METRIC_CALC_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS": 20}),
            # The only attempt hangs until Temporal ends it from the outside.
            (
                "last_attempt_killed_by_start_to_close",
                True,
                {"METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS": 1, "MAX_METRIC_ATTEMPTS": 1},
            ),
        ]
    )
    async def test_metric_ended_by_temporal_runs_the_failure_backstop(
        self, name: str, hangs: bool, workflow_overrides: dict[str, int]
    ):
        activities, _progress, _calls = _make_mock_activities(metrics=[_metric("m1"), _metric("m2")])
        mock_backstop, backstop_calls = _mock_out_of_time_backstop()
        attempts = 0

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            role: str = "primary",
        ) -> MetricRecalculationResult:
            nonlocal attempts
            if metric_uuid == "m2":
                return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)
            attempts += 1
            if hangs:
                await asyncio.sleep(3600)
            raise RuntimeError("transient blip")

        with ExitStack() as stack:
            for name, value in workflow_overrides.items():
                stack.enter_context(patch(f"{_WORKFLOW_MODULE}.{name}", value))
            result = await _run_workflow([*activities[:2], mock_calculate, mock_backstop])

        assert result == {"total": 2, "succeeded": 1, "failed": 1}
        assert attempts < MAX_METRIC_ATTEMPTS
        assert [(f.experiment_id, f.metric_uuid, f.role) for f in backstop_calls] == [(1, "m1", "primary")]

    async def test_workflow_cancel_reaches_the_running_calc_and_kills_its_query(self):
        activities, _progress, _calls = _make_mock_activities(metrics=[_metric("m1")])
        body_started = asyncio.Event()
        query_killed = asyncio.Event()

        async def slow_sync(*args: object) -> MetricRecalculationResult:
            body_started.set()
            await query_killed.wait()
            return MetricRecalculationResult(metric_uuid="m1", success=True)

        async def fake_kill(recalculation_id: str, metric_uuid: str, attempt: int) -> None:
            query_killed.set()

        task_queue = str(uuid.uuid4())
        with (
            patch(f"{_ACTIVITIES_MODULE}._calculate_experiment_metric_for_recalculation_sync", new=slow_sync),
            patch(f"{_ACTIVITIES_MODULE}._cancel_metric_query_sync", new=fake_kill),
            patch(f"{_WORKFLOW_MODULE}.METRIC_CALC_HEARTBEAT_TIMEOUT_SECONDS", 8),
        ):
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[ExperimentMetricsRecalculationWorkflow],
                    activities=[*activities[:2], calculate_experiment_metric_for_recalculation],
                    workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
                ):
                    handle = await env.client.start_workflow(
                        ExperimentMetricsRecalculationWorkflow.run,
                        ExperimentMetricsRecalculationWorkflowInputs(recalculation_id=str(uuid.uuid4())),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )
                    await asyncio.wait_for(body_started.wait(), timeout=10)
                    await handle.cancel()

                    # Shorter than the heartbeat timeout, so a missed heartbeat cannot end the attempt first:
                    # only a heartbeat response can deliver the cancel in time.
                    await asyncio.wait_for(query_killed.wait(), timeout=6)
                    with pytest.raises(WorkflowFailureError):
                        await handle.result()

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
            role: str = "primary",
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
            role: str = "primary",
        ) -> MetricRecalculationResult:
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        with pytest.raises(WorkflowFailureError) as exc_info:
            await _run_workflow([mock_discover, progress_returning_none, mock_calculate])

        cause = exc_info.value.cause
        assert isinstance(cause, ApplicationError)
        assert cause.non_retryable is True
        assert "expected str" in str(cause)

    async def test_failure_before_finalize_records_terminal_failed_status(self):
        # A failure after the workflow starts but before it finalizes (here: discovery raises) must still leave
        # the job row terminal. The workflow catches the error, writes status=failed via the progress activity,
        # then re-raises so Temporal still sees the run as failed. Without this backstop the row stays
        # non-terminal and the UI polls it until the 30-min staleness TTL reaps it (the orphan we are guarding).
        progress_updates: list[RecalculationProgressUpdate] = []

        @activity.defn(name="discover_experiment_metrics")
        async def failing_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            raise ApplicationError("discovery boom", non_retryable=True)

        @activity.defn(name="update_recalculation_progress")
        async def mock_update_progress(update: RecalculationProgressUpdate) -> str | None:
            progress_updates.append(update)
            return _START_QUERY_TO if update.mark_started else None

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            role: str = "primary",
        ) -> MetricRecalculationResult:
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        with pytest.raises(WorkflowFailureError):
            await _run_workflow([failing_discover, mock_update_progress, mock_calculate])

        # Exactly the terminal-fail write: the backstop marks the run completed with status=failed even though
        # discovery never produced metrics or a mark_started call.
        assert len(progress_updates) == 1
        assert progress_updates[0].mark_completed is True
        assert progress_updates[0].mark_started is False
        assert progress_updates[0].status == "failed"

    async def test_finalize_write_failure_records_real_status_not_failed(self):
        # A run where every metric succeeded, but the finalize write (mark_completed, status=completed) exhausts
        # its retries. The workflow must record the REAL status via the finalize-failure backstop, not let
        # run()'s except overwrite it with a spurious "failed" (which would mislabel a healthy run).
        progress_updates: list[RecalculationProgressUpdate] = []
        finalize_attempts = {"count": 0}

        @activity.defn(name="discover_experiment_metrics")
        async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            return [_metric("m1")]

        @activity.defn(name="update_recalculation_progress")
        async def mock_update_progress(update: RecalculationProgressUpdate) -> str | None:
            # Fail the finish write (mark_completed) hard on its first invocation to simulate the finalize
            # activity exhausting its retries; the workflow's finalize-failure path then re-writes via the
            # backstop, which we let succeed.
            if update.mark_completed and finalize_attempts["count"] == 0:
                finalize_attempts["count"] += 1
                raise ApplicationError("finalize boom", non_retryable=True)
            progress_updates.append(update)
            return _START_QUERY_TO if update.mark_started else None

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            role: str = "primary",
        ) -> MetricRecalculationResult:
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        result = await _run_workflow([mock_discover, mock_update_progress, mock_calculate])

        # The run is recorded completed with the real counts, NOT failed.
        assert result == {"total": 1, "succeeded": 1, "failed": 0}
        terminal = progress_updates[-1]
        assert terminal.mark_completed is True
        assert terminal.status == "completed"
        assert terminal.succeeded_metrics == 1
        assert terminal.failed_metrics == 0

    async def test_finalize_and_backstop_both_failing_fails_the_workflow(self):
        # The finalize write AND the backstop write both exhaust their retries (every mark_completed throws).
        # The workflow must FAIL, not swallow the error and report success on a non-terminal row; the row's
        # terminality then falls to the interceptor + staleness TTL, as it did before the terminal-state wrapper.
        @activity.defn(name="discover_experiment_metrics")
        async def mock_discover(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
            return [_metric("m1")]

        @activity.defn(name="update_recalculation_progress")
        async def mock_update_progress(update: RecalculationProgressUpdate) -> str | None:
            # Every terminal write fails (finalize and its backstop), only mark_started succeeds.
            if update.mark_completed:
                raise ApplicationError("terminal write down", non_retryable=True)
            return _START_QUERY_TO if update.mark_started else None

        @activity.defn(name="calculate_experiment_metric_for_recalculation")
        async def mock_calculate(
            experiment_id: int,
            metric_uuid: str,
            recalculation_id: str,
            query_to: str,
            role: str = "primary",
        ) -> MetricRecalculationResult:
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        with pytest.raises(WorkflowFailureError):
            await _run_workflow([mock_discover, mock_update_progress, mock_calculate])

    @parameterized.expand(
        [
            # name, set_field, expected_workflow_queue_calls, expected_activity_queue_calls
            ("field_unset_stays_on_workflow_queue", False, ["m1"], []),
            ("field_set_routes_to_activity_queue", True, [], ["m1"]),
        ]
    )
    async def test_activity_task_queue_routes_the_calculation(
        self,
        name: str,
        set_field: bool,
        expected_workflow_queue_calls: list[str],
        expected_activity_queue_calls: list[str],
    ):
        activity_worker_task_queue = str(uuid.uuid4())
        run = await _run_with_activity_queue_worker(
            activity_task_queue=activity_worker_task_queue if set_field else None,
            activity_worker_task_queue=activity_worker_task_queue,
        )

        assert run.result == {"total": 1, "succeeded": 1, "failed": 0}
        assert run.workflow_queue_calls == expected_workflow_queue_calls
        assert run.activity_queue_calls == expected_activity_queue_calls

    async def test_pre_patch_history_with_the_field_set_replays(self):
        # An old worker ignores the unknown input field and records no patch marker, so the new code must
        # replay that history with the calculation on the workflow's queue.
        activity_worker_task_queue = str(uuid.uuid4())
        original_patched = temporalio.workflow.patched

        def pre_patch(patch_id: str) -> bool:
            return False if patch_id == "recalc-activity-task-queue-2026-10" else original_patched(patch_id)

        with patch.object(temporalio.workflow, "patched", side_effect=pre_patch):
            run = await _run_with_activity_queue_worker(
                activity_task_queue=activity_worker_task_queue,
                activity_worker_task_queue=activity_worker_task_queue,
            )

        assert run.workflow_queue_calls == ["m1"]
        assert run.activity_queue_calls == []
        await temporalio.worker.Replayer(
            workflows=[ExperimentMetricsRecalculationWorkflow],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ).replay_workflow(run.history)
