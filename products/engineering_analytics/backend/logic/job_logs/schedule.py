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

from posthog.scheduling.jitter import deterministic_offset
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

SCHEDULE_ID = "github-job-logs-coordinator-schedule"
SCHEDULE_INTERVAL = timedelta(minutes=2)


async def create_github_job_logs_coordinator_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "github-job-logs-coordinator",
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=SCHEDULE_INTERVAL, offset=deterministic_offset(SCHEDULE_ID, SCHEDULE_INTERVAL)
                )
            ]
        ),
        # SKIP so that a slow tick does not stack. The egress limiter caps spend, not the interval.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
