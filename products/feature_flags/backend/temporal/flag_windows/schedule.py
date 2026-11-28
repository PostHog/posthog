from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.feature_flags.backend.temporal.flag_windows.types import TICK_FLAG_WINDOWS_WORKFLOW, TickFlagWindowsInputs

SCHEDULE_ID = "feature-flags-tick-flag-windows-schedule"
SCHEDULE_INTERVAL = timedelta(minutes=15)


async def create_tick_flag_windows_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TICK_FLAG_WINDOWS_WORKFLOW,
            TickFlagWindowsInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL, offset=timedelta(minutes=2))],
            jitter=timedelta(minutes=2),
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
