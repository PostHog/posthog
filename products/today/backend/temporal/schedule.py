"""Temporal schedule that starts briefings shortly before 8:00 in each person's timezone."""

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

from .activities import SCHEDULE_WINDOW_MINUTES
from .inputs import SCHEDULER_WORKFLOW_NAME, SchedulerInputs

_SCHEDULE_ID = "today-briefing-scheduler"
_WORKFLOW_ID = "today-briefing-scheduler"


async def create_today_briefing_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SCHEDULER_WORKFLOW_NAME,
            SchedulerInputs(),
            id=_WORKFLOW_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=timedelta(minutes=SCHEDULE_WINDOW_MINUTES),
        ),
        # nosemgrep: schedule-must-avoid-minute-zero -- each run writes the briefings that start in the next window, so an offset shortens how far ahead of 8:00 local a briefing is written
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=SCHEDULE_WINDOW_MINUTES))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, _SCHEDULE_ID):
        description = await client.get_schedule_handle(_SCHEDULE_ID).describe()
        schedule.state = description.schedule.state
        await a_update_schedule(client, _SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, _SCHEDULE_ID, schedule, trigger_immediately=False)
