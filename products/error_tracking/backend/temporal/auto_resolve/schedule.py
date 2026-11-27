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

from products.error_tracking.backend.temporal.auto_resolve.workflow import WORKFLOW_NAME, AutoResolveInputs


async def create_error_tracking_auto_resolve_schedules(client: Client) -> None:
    schedule_id = "error-tracking-auto-resolve-schedule"
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME, AutoResolveInputs(), id=schedule_id, task_queue=settings.ERROR_TRACKING_TASK_QUEUE
        ),
        spec=ScheduleSpec(calendars=[ScheduleCalendarSpec(hour=[ScheduleRange(start=6)])]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(days=1)),
    )
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule, keep_paused=True)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)
