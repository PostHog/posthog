import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings

from temporalio.client import ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleOverlapPolicy

from products.error_tracking.backend.temporal.symbol_set_cleanup.schedule import (
    SCHEDULE_ID,
    SCHEDULE_INTERVAL,
    create_error_tracking_symbol_set_cleanup_schedule,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup.types import SymbolSetCleanupInputs
from products.error_tracking.backend.temporal.symbol_set_cleanup.workflow import WORKFLOW_NAME


@pytest.fixture
def schedule_helpers():
    with (
        patch(
            "products.error_tracking.backend.temporal.symbol_set_cleanup.schedule.a_create_schedule",
            new_callable=AsyncMock,
        ) as create,
        patch(
            "products.error_tracking.backend.temporal.symbol_set_cleanup.schedule.a_update_schedule",
            new_callable=AsyncMock,
        ) as update,
        patch(
            "products.error_tracking.backend.temporal.symbol_set_cleanup.schedule.a_schedule_exists",
            new_callable=AsyncMock,
        ) as exists,
    ):
        yield {"create": create, "update": update, "exists": exists}


@pytest.fixture
def mock_client():
    return object()


def assert_symbol_set_cleanup_schedule(schedule) -> None:
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.workflow == WORKFLOW_NAME
    assert schedule.action.args == [SymbolSetCleanupInputs()]
    assert schedule.action.id == SCHEDULE_ID
    assert schedule.action.task_queue == settings.ERROR_TRACKING_TASK_QUEUE
    assert schedule.policy is not None
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == SCHEDULE_INTERVAL
    assert schedule.spec.intervals == [ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]


class TestCreateErrorTrackingSymbolSetCleanupSchedule:
    @pytest.mark.asyncio
    async def test_creates_hourly_schedule_when_missing(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = False

        await create_error_tracking_symbol_set_cleanup_schedule(mock_client)

        schedule_helpers["create"].assert_awaited_once()
        schedule_helpers["update"].assert_not_called()
        client, schedule_id, schedule = schedule_helpers["create"].call_args.args
        assert client is mock_client
        assert schedule_id == SCHEDULE_ID
        assert schedule_helpers["create"].call_args.kwargs["trigger_immediately"] is False

        assert_symbol_set_cleanup_schedule(schedule)

    @pytest.mark.asyncio
    async def test_updates_existing_schedule(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = True

        await create_error_tracking_symbol_set_cleanup_schedule(mock_client)

        schedule_helpers["create"].assert_not_called()
        schedule_helpers["update"].assert_awaited_once()
        client, schedule_id, schedule = schedule_helpers["update"].call_args.args
        assert client is mock_client
        assert schedule_id == SCHEDULE_ID
        assert_symbol_set_cleanup_schedule(schedule)
