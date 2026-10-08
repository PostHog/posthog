import uuid
import asyncio
import dataclasses

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.exceptions import ActivityError
from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.temporal.data_imports import person_property_backfill_job as bj
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertyBackfillActivityInputs,
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


def _activity_error() -> ActivityError:
    """What ``execute_activity`` raises once the activity exhausts its single attempt."""
    return ActivityError(
        "backfill failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type="backfill-warehouse-person-properties",
        activity_id="1",
        retry_state=None,
    )


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
    ):
        running = asyncio.create_task(runner.run(seed))
        await first_started.wait()
        await runner.request_backfill(middle)
        await runner.request_backfill(latest)
        release_first.set()
        await running

    assert observed == [first, latest]


@pytest.mark.asyncio
async def test_a_failed_run_still_serves_a_request_that_arrived_while_it_ran() -> None:
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

    async def execute_activity(_activity, inputs, **_kwargs):
        observed.append(inputs)
        if len(observed) == 1:
            first_started.set()
            await release_first.wait()
            raise _activity_error()

    with (
        patch.object(bj.workflow, "execute_activity", AsyncMock(side_effect=execute_activity)),
        patch.object(bj.workflow, "wait_condition", AsyncMock()),
    ):
        running = asyncio.create_task(runner.run(seed))
        await first_started.wait()
        await runner.request_backfill(latest)
        release_first.set()
        await running

    assert observed == [first, latest]


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
        pytest.raises(ActivityError),
    ):
        await runner.run(seed)

    assert observed == [only]
