import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings

from temporalio.client import ScheduleActionStartWorkflow, ScheduleCalendarSpec, ScheduleOverlapPolicy, ScheduleRange

from products.error_tracking.backend.temporal.weekly_digest.schedule import (
    SCHEDULE_CATCHUP_WINDOW,
    SCHEDULE_ID,
    create_error_tracking_weekly_digest_schedule,
)
from products.error_tracking.backend.temporal.weekly_digest.types import WeeklyDigestInputs
from products.error_tracking.backend.temporal.weekly_digest.workflow import WORKFLOW_NAME


@pytest.fixture
def schedule_helpers():
    with (
        patch(
            "products.error_tracking.backend.temporal.weekly_digest.schedule.a_create_schedule",
            new_callable=AsyncMock,
        ) as create,
        patch(
            "products.error_tracking.backend.temporal.weekly_digest.schedule.a_update_schedule",
            new_callable=AsyncMock,
        ) as update,
        patch(
            "products.error_tracking.backend.temporal.weekly_digest.schedule.a_schedule_exists",
            new_callable=AsyncMock,
        ) as exists,
    ):
        yield {"create": create, "update": update, "exists": exists}


@pytest.fixture
def mock_client():
    return object()


def assert_weekly_digest_schedule(schedule) -> None:
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.workflow == WORKFLOW_NAME
    # The scheduled run is the one caller that must send for real: dry_run defaults to
    # True everywhere else as a manual-run fail-safe.
    assert schedule.action.args == [WeeklyDigestInputs(dry_run=False)]
    assert schedule.action.id == SCHEDULE_ID
    assert schedule.action.task_queue == settings.ERROR_TRACKING_TASK_QUEUE
    assert schedule.action.retry_policy is not None
    assert schedule.action.retry_policy.maximum_attempts == 1
    assert schedule.policy is not None
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == SCHEDULE_CATCHUP_WINDOW
    assert schedule.spec.calendars == [
        ScheduleCalendarSpec(
            comment="Mondays at 08:30 UTC",
            day_of_week=[ScheduleRange(start=1, end=1)],
            hour=[ScheduleRange(start=8, end=8)],
            minute=[ScheduleRange(start=30, end=30)],
        )
    ]


class TestCreateErrorTrackingWeeklyDigestSchedule:
    @pytest.mark.asyncio
    async def test_creates_weekly_schedule_when_missing(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = False

        await create_error_tracking_weekly_digest_schedule(mock_client)

        schedule_helpers["create"].assert_awaited_once()
        schedule_helpers["update"].assert_not_called()
        client, schedule_id, schedule = schedule_helpers["create"].call_args.args
        assert client is mock_client
        assert schedule_id == SCHEDULE_ID
        assert schedule_helpers["create"].call_args.kwargs["trigger_immediately"] is False

        assert_weekly_digest_schedule(schedule)

    @pytest.mark.asyncio
    async def test_updates_existing_schedule(self, mock_client, schedule_helpers) -> None:
        schedule_helpers["exists"].return_value = True

        await create_error_tracking_weekly_digest_schedule(mock_client)

        schedule_helpers["create"].assert_not_called()
        schedule_helpers["update"].assert_awaited_once()
        client, schedule_id, schedule = schedule_helpers["update"].call_args.args
        assert client is mock_client
        assert schedule_id == SCHEDULE_ID
        assert_weekly_digest_schedule(schedule)
