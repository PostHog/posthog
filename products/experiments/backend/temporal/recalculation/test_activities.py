"""Tests for the cancel path of the calculate activity entrypoint."""

import asyncio
import threading
import dataclasses
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.tests.utils.asyncify import restored_asyncify_executor

from products.experiments.backend.temporal.models import MetricRecalculationResult
from products.experiments.backend.temporal.recalculation.activities import calculate_experiment_metric_for_recalculation
from products.experiments.backend.temporal.recalculation.calculation import _cancel_metric_query_sync

from . import test_helpers


def _start_activity(env: ActivityEnvironment) -> asyncio.Task[MetricRecalculationResult]:
    return asyncio.create_task(
        env.run(calculate_experiment_metric_for_recalculation, 1, "m1", "r1", test_helpers._QUERY_TO)
    )


class TestCalculateActivityCancellation:
    @contextmanager
    def _patched_boundaries(self, body, cancel_query):
        with (
            patch(
                "products.experiments.backend.temporal.recalculation.activities._calculate_experiment_metric_for_recalculation_sync",
                body,
            ),
            patch("products.experiments.backend.temporal.recalculation.activities.on_asyncify_pool", lambda fn: fn),
            patch(
                "products.experiments.backend.temporal.recalculation.activities._cancel_metric_query_sync", cancel_query
            ),
            patch(
                "products.experiments.backend.temporal.recalculation.activities._CANCEL_KILL_RETRY_INTERVAL_SECONDS",
                0.001,
            ),
        ):
            yield

    @pytest.mark.parametrize("cancellations", [1, 2])
    @pytest.mark.parametrize("body_fails", [False, True])
    async def test_cancellation_drains_the_body_before_propagating(self, cancellations: int, body_fails: bool) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        body_finished = False

        async def _slow_body(*args: object, **kwargs: object) -> MetricRecalculationResult:
            nonlocal body_finished
            started.set()
            await release.wait()
            body_finished = True
            if body_fails:
                raise RuntimeError("calculation failed during cleanup")
            return MetricRecalculationResult(metric_uuid="m1", success=True)

        with self._patched_boundaries(_slow_body, AsyncMock()):
            task = _start_activity(ActivityEnvironment())
            await started.wait()
            try:
                for cancellation in range(cancellations):
                    task.cancel(f"cancel-{cancellation}")
                    await asyncio.sleep(0)
                    assert not task.done()
            finally:
                release.set()

            with pytest.raises(asyncio.CancelledError, match="cancel-0"):
                await task

        assert body_finished is True

    async def test_cancellation_drain_has_a_deadline(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        body_finished = asyncio.Event()
        cancel_query = AsyncMock()

        async def _slow_body(*args: object, **kwargs: object) -> MetricRecalculationResult:
            started.set()
            await release.wait()
            body_finished.set()
            return MetricRecalculationResult(metric_uuid="m1", success=True)

        with (
            self._patched_boundaries(_slow_body, cancel_query),
            patch(
                "products.experiments.backend.temporal.recalculation.activities.METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS", 0
            ),
        ):
            task = _start_activity(ActivityEnvironment())
            await started.wait()
            try:
                task.cancel("original cancellation")
                with pytest.raises(asyncio.CancelledError, match="original cancellation"):
                    await asyncio.wait_for(task, timeout=5)
                assert not body_finished.is_set()
                assert cancel_query.await_count == 1
            finally:
                release.set()
                await asyncio.wait_for(body_finished.wait(), timeout=5)

    async def _cancel_during_body(self, kills_until_query_dies: int = 1) -> dict:
        started = asyncio.Event()
        query_died = asyncio.Event()
        observed: dict = {
            "body_finished": False,
            "cancel_calls": 0,
            "cancel_args": None,
            "cancelled_before_body_finished": None,
        }

        async def _slow_body(*args: object, **kwargs: object) -> MetricRecalculationResult:
            started.set()
            await query_died.wait()
            observed["body_finished"] = True
            return MetricRecalculationResult(metric_uuid="m1", success=True)

        async def _fake_cancel_query(recalculation_id: str, metric_uuid: str, attempt: int) -> None:
            observed["cancel_calls"] += 1
            observed["cancel_args"] = (recalculation_id, metric_uuid, attempt)
            observed["cancelled_before_body_finished"] = not observed["body_finished"]
            if observed["cancel_calls"] == kills_until_query_dies:
                query_died.set()

        with (
            self._patched_boundaries(_slow_body, _fake_cancel_query),
            patch(
                "products.experiments.backend.temporal.recalculation.activities.METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS", 1
            ),
        ):
            task = _start_activity(ActivityEnvironment())
            await started.wait()
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

        return observed

    async def test_cancellation_kills_the_running_clickhouse_query_first(self) -> None:
        # Without the kill the drain waits out the query's full max_execution_time, and ClickHouse keeps reading
        # for an attempt whose result nothing will use.
        observed = await self._cancel_during_body()

        assert observed["cancel_args"] == ("r1", "m1", 1)
        assert observed["cancelled_before_body_finished"] is True

    async def test_cancellation_retries_the_kill_when_the_first_one_misses(self) -> None:
        # A cancel that lands during the body's Postgres phase kills before ClickHouse registers the query, so
        # the first kill finds nothing.
        observed = await self._cancel_during_body(kills_until_query_dies=2)

        assert observed["cancel_calls"] == 2
        assert observed["body_finished"] is True

    async def test_query_kill_runs_while_calculations_fill_the_default_executor(self) -> None:
        calculations_running = threading.Event()
        killed: list[str] = []
        busy_default_executor = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(busy_default_executor)
        busy_default_executor.submit(calculations_running.wait)
        try:
            with (
                patch("products.experiments.backend.temporal.recalculation.calculation.close_old_connections"),
                patch(
                    "products.experiments.backend.temporal.recalculation.run_state._get_recalc_state",
                    return_value=SimpleNamespace(team_id=1),
                ),
                patch(
                    "products.experiments.backend.temporal.recalculation.calculation.cancel_query_on_cluster",
                    lambda team_id, query_id: killed.append(query_id),
                ),
            ):
                await asyncio.wait_for(_cancel_metric_query_sync("r1", "m1", 1), timeout=5)
        finally:
            calculations_running.set()

        assert killed == ["experiment_metric_recalc_r1_m1_attempt01"]

    async def test_calculation_runs_while_the_default_executor_is_full(self) -> None:
        # The default executor has node CPUs + 4 threads, so calculations there run fewer at once than the worker's slots.
        default_executor_full = threading.Event()
        busy_default_executor = ThreadPoolExecutor(max_workers=1)
        asyncio.get_running_loop().set_default_executor(busy_default_executor)
        busy_default_executor.submit(default_executor_full.wait)
        try:
            with (
                restored_asyncify_executor() as configure_asyncify_executor,
                patch("products.experiments.backend.temporal.recalculation.calculation.close_old_connections"),
                patch(
                    "products.experiments.backend.temporal.recalculation.activities._cancel_metric_query_sync",
                    AsyncMock(),
                ),
                patch(
                    "products.experiments.backend.temporal.recalculation.activities.METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS",
                    0,
                ),
            ):
                configure_asyncify_executor(1)
                with pytest.raises(ApplicationError, match="not a valid ISO datetime"):
                    await asyncio.wait_for(
                        ActivityEnvironment().run(
                            calculate_experiment_metric_for_recalculation, 1, "m1", "r1", "not-a-date"
                        ),
                        timeout=5,
                    )
        finally:
            default_executor_full.set()

    async def test_heartbeats_while_the_body_runs_and_stops_after(self) -> None:
        # Temporal delivers a cancellation only in a heartbeat response, so without heartbeats the drain above
        # never runs for a workflow cancel or a server-side timeout.
        heartbeats = 0
        two_heartbeats = asyncio.Event()

        def _on_heartbeat(*details: object) -> None:
            nonlocal heartbeats
            heartbeats += 1
            if heartbeats >= 2:
                two_heartbeats.set()

        async def _body(*args: object, **kwargs: object) -> MetricRecalculationResult:
            await two_heartbeats.wait()
            return MetricRecalculationResult(metric_uuid="m1", success=True)

        env = ActivityEnvironment()
        env.info = dataclasses.replace(env.info, heartbeat_timeout=timedelta(seconds=0.2))
        env.on_heartbeat = _on_heartbeat
        tasks_before = asyncio.all_tasks()
        with self._patched_boundaries(_body, AsyncMock()):
            result = await asyncio.wait_for(_start_activity(env), timeout=5)

        assert result.success is True
        assert asyncio.all_tasks() - tasks_before == set()

    async def test_body_gets_the_task_queue_the_worker_polls(self) -> None:
        body = AsyncMock(return_value=MetricRecalculationResult(metric_uuid="m1", success=True))
        env = ActivityEnvironment()
        env.info = dataclasses.replace(env.info, task_queue="activity-q")

        with self._patched_boundaries(body, AsyncMock()):
            await _start_activity(env)

        assert body.call_args.args[-1] == "activity-q"
