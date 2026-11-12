import uuid
import asyncio
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError, TimeoutType
from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.temporal.data_imports import person_property_backfill_job as bj
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertyBackfillActivityInputs,
    PersonPropertyFailedRunInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_sync import SyncResult


def _inputs(team_id: int) -> PersonPropertyBackfillActivityInputs:
    return PersonPropertyBackfillActivityInputs(
        team_id=team_id,
        schema_id=uuid.uuid4(),
        source_type="Stripe",
        schema_name="charges",
        trigger="manual",
    )


def _activity_error(cause: Exception | None = None) -> ActivityError:
    error = ActivityError(
        "backfill failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type="backfill-warehouse-person-properties",
        activity_id="1",
        retry_state=None,
    )
    error.__cause__ = cause
    return error


@pytest.mark.django_db(transaction=True)
class TestBackfillWarehousePersonPropertiesActivity:
    async def test_records_one_stage_per_nonzero_funnel_count(self) -> None:
        # A distinct team_id per test keeps the module-level Counter's label values from a previous
        # test run bleeding into this one's assertions.
        team_id = 900001
        result = SyncResult(sources=1, rows_read=5, changed=3, existing=0, produced=3, skipped_missing_person=1)
        with (
            patch.object(bj, "run_person_property_backfill", AsyncMock(return_value=result)),
            patch.object(bj, "record_started_runs", AsyncMock()) as mock_started,
            patch.object(bj, "record_completed_runs", AsyncMock()) as mock_record,
        ):
            returned = await ActivityEnvironment().run(
                bj.backfill_warehouse_person_properties_activity, _inputs(team_id)
            )

        assert returned == {
            "sources": 1,
            "rows_read": 5,
            "changed": 3,
            "existing": 0,
            "produced": 3,
            "skipped_missing_person": 1,
            "per_source": [],
        }
        mock_started.assert_awaited_once()
        mock_record.assert_awaited_once()

        def stage_value(stage: str) -> float:
            return bj.PERSON_PROPERTY_BACKFILL_ROWS_TOTAL.labels(team_id=str(team_id), stage=stage)._value.get()

        # Every nonzero stage got its count.
        assert stage_value("read") == 5
        assert stage_value("changed") == 3
        assert stage_value("produced") == 3
        assert stage_value("skipped_missing_person") == 1
        # A zero-count stage is skipped rather than recorded as a no-op increment, so the label
        # never appears on a backfill that didn't touch it.
        assert stage_value("existing") == 0

    async def test_read_rows_with_no_changes_still_recorded(self) -> None:
        # Regression: a backfill that reads rows but changes/produces nothing (the "no metrics but
        # logs" gap this metric exists to close) must still report the read count.
        team_id = 900002
        result = SyncResult(sources=1, rows_read=10, changed=0, existing=10, produced=0, skipped_missing_person=0)
        with (
            patch.object(bj, "run_person_property_backfill", AsyncMock(return_value=result)),
            patch.object(bj, "record_completed_runs", AsyncMock()),
        ):
            await ActivityEnvironment().run(bj.backfill_warehouse_person_properties_activity, _inputs(team_id))

        def stage_value(stage: str) -> float:
            return bj.PERSON_PROPERTY_BACKFILL_ROWS_TOTAL.labels(team_id=str(team_id), stage=stage)._value.get()

        assert stage_value("read") == 10
        assert stage_value("existing") == 10
        assert stage_value("changed") == 0
        assert stage_value("produced") == 0

    @pytest.mark.parametrize("workflow_records_failure,expected_records", [(False, 1), (True, 0)])
    async def test_activity_records_its_own_failure_only_for_workflows_that_do_not(
        self, workflow_records_failure: bool, expected_records: int
    ) -> None:
        inputs = dataclasses.replace(_inputs(900003), workflow_records_failure=workflow_records_failure)
        with (
            patch.object(bj, "run_person_property_backfill", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(bj, "record_started_runs", AsyncMock()),
            patch.object(bj, "record_failed_runs", AsyncMock()) as mock_failed,
            patch.object(bj, "capture_exception"),
            pytest.raises(RuntimeError),
        ):
            await ActivityEnvironment().run(bj.backfill_warehouse_person_properties_activity, inputs)

        assert mock_failed.await_count == expected_records


@pytest.mark.asyncio
async def test_in_flight_backfill_runs_one_follow_up_with_the_latest_request() -> None:
    first = _inputs(900003)
    middle = dataclasses.replace(first, schema_name="users-v2")
    latest = dataclasses.replace(first, schema_name="users-v3")
    seed = dataclasses.replace(first, skip_initial_run=True)
    runner = bj.BackfillWarehousePersonPropertiesWorkflow(seed)
    await runner.request_backfill(first)

    first_started = asyncio.Event()
    release_first = asyncio.Event()
    observed: list[PersonPropertyBackfillActivityInputs] = []

    async def execute_activity(_activity, inputs, **_kwargs):
        observed.append(inputs)
        if len(observed) == 1:
            first_started.set()
            await release_first.wait()

    with (
        patch.object(bj.workflow, "execute_activity", AsyncMock(side_effect=execute_activity)),
        patch.object(bj.workflow, "wait_condition", AsyncMock()),
        patch.object(bj.workflow, "now", return_value=datetime(2026, 10, 1, tzinfo=UTC)),
        patch.object(bj.workflow, "patched", return_value=False),
    ):
        running = asyncio.create_task(runner.run(seed))
        await first_started.wait()
        await runner.request_backfill(middle)
        await runner.request_backfill(latest)
        release_first.set()
        await running

    assert observed == [first, latest]


@pytest.mark.asyncio
@pytest.mark.parametrize("records_failure", [False, True])
async def test_a_failed_run_still_serves_a_request_that_arrived_while_it_ran(records_failure: bool) -> None:
    # The API reports a request that lands mid-run as queued, so losing it with the run it happened
    # to overlap would strand a mapping edit with nothing telling the user.
    first = _inputs(900004)
    latest = dataclasses.replace(first, schema_name="users-v2")
    seed = dataclasses.replace(first, skip_initial_run=True)
    runner = bj.BackfillWarehousePersonPropertiesWorkflow(seed)
    await runner.request_backfill(first)

    first_started = asyncio.Event()
    release_first = asyncio.Event()
    observed: list[PersonPropertyBackfillActivityInputs] = []

    async def execute_activity(activity_fn, inputs, **_kwargs):
        if activity_fn is bj.record_failed_person_property_backfill_runs_activity:
            # The failed-run record can itself be lost to a worker shutdown.
            raise _activity_error()
        observed.append(inputs)
        if len(observed) == 1:
            first_started.set()
            await release_first.wait()
            raise _activity_error()

    with (
        patch.object(bj.workflow, "execute_activity", AsyncMock(side_effect=execute_activity)),
        patch.object(bj.workflow, "wait_condition", AsyncMock()),
        patch.object(bj.workflow, "now", return_value=datetime(2026, 10, 1, tzinfo=UTC)),
        patch.object(bj.workflow, "patched", return_value=records_failure),
        patch.object(bj.workflow, "logger"),
    ):
        running = asyncio.create_task(runner.run(seed))
        await first_started.wait()
        await runner.request_backfill(latest)
        release_first.set()
        await running

    assert [i.schema_name for i in observed] == [first.schema_name, latest.schema_name]


@pytest.mark.asyncio
async def test_a_failed_run_with_nothing_queued_fails_the_workflow() -> None:
    # Swallowing the failure outright would report a backfill that never ran as a clean completion.
    only = _inputs(900005)
    seed = dataclasses.replace(only, skip_initial_run=True)
    runner = bj.BackfillWarehousePersonPropertiesWorkflow(seed)
    await runner.request_backfill(only)

    observed: list[PersonPropertyBackfillActivityInputs] = []

    async def execute_activity(_activity, inputs, **_kwargs):
        observed.append(inputs)
        raise _activity_error()

    with (
        patch.object(bj.workflow, "execute_activity", AsyncMock(side_effect=execute_activity)),
        patch.object(bj.workflow, "wait_condition", AsyncMock()),
        patch.object(bj.workflow, "now", return_value=datetime(2026, 10, 1, tzinfo=UTC)),
        patch.object(bj.workflow, "patched", return_value=False),
        pytest.raises(ActivityError),
    ):
        await runner.run(seed)

    assert observed == [only]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause,failures,patch_enabled,expected_attempts",
    [
        (ApplicationError("Worker stopped", type="WorkerShutdown"), 1, True, 2),
        (ApplicationError("Worker stopped", type="WorkerShutdown"), 2, True, 3),
        (ApplicationError("Worker stopped", type="WorkerShutdown"), 3, True, 3),
        (TimeoutError("No heartbeat", type=TimeoutType.HEARTBEAT, last_heartbeat_details=[]), 1, True, 2),
        (TimeoutError("No heartbeat", type=TimeoutType.HEARTBEAT, last_heartbeat_details=[]), 3, True, 3),
        (TimeoutError("Too slow", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]), 1, True, 1),
        (ApplicationError("Invalid mapping", type="ValueError"), 1, True, 1),
        (ApplicationError("Worker stopped", type="WorkerShutdown"), 1, False, 1),
    ],
)
async def test_interrupted_backfill_retries_only_worker_shutdowns_and_heartbeat_timeouts(
    cause: Exception, failures: int, patch_enabled: bool, expected_attempts: int
) -> None:
    inputs = _inputs(900006)
    runner = bj.BackfillWarehousePersonPropertiesWorkflow(inputs)
    attempts = 0
    failed_records: list[PersonPropertyFailedRunInputs] = []

    async def execute_activity(
        activity_fn: Callable[..., object],
        activity_inputs: PersonPropertyBackfillActivityInputs | PersonPropertyFailedRunInputs,
        **_kwargs: object,
    ) -> None:
        nonlocal attempts
        if activity_fn is bj.record_failed_person_property_backfill_runs_activity:
            assert isinstance(activity_inputs, PersonPropertyFailedRunInputs)
            failed_records.append(activity_inputs)
            return
        attempts += 1
        if attempts <= failures:
            raise _activity_error(cause)

    def patched(patch_id: str) -> bool:
        return patch_enabled if patch_id == bj.RETRY_INTERRUPTED_RUN_PATCH else True

    with (
        patch.object(bj.workflow, "execute_activity", AsyncMock(side_effect=execute_activity)),
        patch.object(bj.workflow, "wait_condition", AsyncMock()),
        patch.object(bj.workflow, "now", return_value=datetime(2026, 10, 1, tzinfo=UTC)),
        patch.object(bj.workflow, "patched", side_effect=patched),
    ):
        if failures >= expected_attempts:
            with pytest.raises(ActivityError):
                await runner.run(inputs)
        else:
            await runner.run(inputs)

    assert attempts == expected_attempts
    assert len(failed_records) == (1 if failures >= expected_attempts else 0)
    if failed_records:
        assert failed_records[0].count_failure == (
            not (isinstance(cause, ApplicationError) and cause.type == "WorkerShutdown")
        )
