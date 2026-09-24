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

from products.error_tracking.backend.temporal.auto_resolve.types import AutoResolveInputs
from products.error_tracking.backend.temporal.auto_resolve.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-auto-resolve-schedule"
SCHEDULE_CATCHUP_WINDOW = timedelta(hours=12)


async def create_error_tracking_auto_resolve_schedule(client: Client) -> None:
    auto_resolve_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            AutoResolveInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 5 AM UTC",
                    hour=[ScheduleRange(start=5, end=5)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_CATCHUP_WINDOW),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, auto_resolve_schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, auto_resolve_schedule, trigger_immediately=False)
