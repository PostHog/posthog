from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.error_tracking.backend.temporal.spike_event_cleanup.types import SpikeEventCleanupInputs
from products.error_tracking.backend.temporal.spike_event_cleanup.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-spike-event-cleanup-schedule"
SCHEDULE_CATCHUP_WINDOW = timedelta(days=1)


async def create_error_tracking_spike_event_cleanup_schedule(client: Client) -> None:
    spike_event_cleanup_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            SpikeEventCleanupInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 4 AM UTC",
                    hour=[ScheduleRange(start=4, end=4)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_CATCHUP_WINDOW),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, spike_event_cleanup_schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, spike_event_cleanup_schedule, trigger_immediately=False)
