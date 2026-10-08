import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings

from products.experiments.backend.temporal.models import SCHEDULED_RECALCULATION_WORKFLOW_NAME
from products.experiments.backend.temporal.schedule import (
    SCHEDULED_RECALCULATION_SCHEDULE_ID,
    create_experiment_scheduled_recalculation_schedules,
)

pytestmark = pytest.mark.asyncio

MODULE = "products.experiments.backend.temporal.schedule"


async def test_creates_one_hourly_schedule_offset_from_the_timeseries_run():
    with (
        patch(f"{MODULE}.a_schedule_exists", AsyncMock(return_value=False)),
        patch(f"{MODULE}.a_create_schedule", AsyncMock()) as create,
        patch(f"{MODULE}.a_update_schedule", AsyncMock()) as update,
    ):
        await create_experiment_scheduled_recalculation_schedules(AsyncMock())

    assert create.await_count == 1
    update.assert_not_awaited()

    # Every field a typo could break: a wrong workflow name or task queue fails only in
    # production, where nothing reports it.
    call = create.await_args_list[0]
    schedule_id, schedule = call.args[1], call.args[2]
    assert schedule_id == SCHEDULED_RECALCULATION_SCHEDULE_ID
    # :30, so the daily timeseries run at :00 publishes before a real run supersedes it.
    assert schedule.spec.cron_expressions == ["30 * * * *"]
    assert schedule.action.workflow == SCHEDULED_RECALCULATION_WORKFLOW_NAME
    assert schedule.action.task_queue == settings.GENERAL_PURPOSE_TASK_QUEUE
    # No input: discovery resolves the hour, so one schedule serves every hour.
    assert schedule.action.args == []


async def test_an_existing_schedule_is_updated_not_recreated():
    with (
        patch(f"{MODULE}.a_schedule_exists", AsyncMock(return_value=True)),
        patch(f"{MODULE}.a_create_schedule", AsyncMock()) as create,
        patch(f"{MODULE}.a_update_schedule", AsyncMock()) as update,
    ):
        await create_experiment_scheduled_recalculation_schedules(AsyncMock())

    assert update.await_count == 1
    create.assert_not_awaited()
