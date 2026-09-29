import pytest
from unittest.mock import AsyncMock, patch

from products.experiments.backend.temporal.schedule import (
    SCHEDULED_RECALCULATION_SCHEDULE_ID_PREFIX,
    create_experiment_scheduled_recalculation_schedules,
)

pytestmark = pytest.mark.asyncio

MODULE = "products.experiments.backend.temporal.schedule"


async def test_creates_one_schedule_per_hour_offset_from_the_timeseries_run():
    with (
        patch(f"{MODULE}.a_schedule_exists", AsyncMock(return_value=False)),
        patch(f"{MODULE}.a_create_schedule", AsyncMock()) as create,
        patch(f"{MODULE}.a_update_schedule", AsyncMock()) as update,
    ):
        await create_experiment_scheduled_recalculation_schedules(AsyncMock())

    assert create.await_count == 24
    update.assert_not_awaited()

    schedule_ids = [call.args[1] for call in create.await_args_list]
    assert schedule_ids[0] == f"{SCHEDULED_RECALCULATION_SCHEDULE_ID_PREFIX}-00"
    assert schedule_ids[23] == f"{SCHEDULED_RECALCULATION_SCHEDULE_ID_PREFIX}-23"

    crons = [call.args[2].spec.cron_expressions[0] for call in create.await_args_list]
    # :30, so the daily timeseries run at :00 publishes before a real run supersedes it.
    assert crons[0] == "30 0 * * *"
    assert crons[23] == "30 23 * * *"

    hours = [call.args[2].action.args[0].hour for call in create.await_args_list]
    assert hours == list(range(24))


async def test_existing_schedules_are_updated_not_recreated():
    with (
        patch(f"{MODULE}.a_schedule_exists", AsyncMock(return_value=True)),
        patch(f"{MODULE}.a_create_schedule", AsyncMock()) as create,
        patch(f"{MODULE}.a_update_schedule", AsyncMock()) as update,
    ):
        await create_experiment_scheduled_recalculation_schedules(AsyncMock())

    assert update.await_count == 24
    create.assert_not_awaited()
