"""Temporal schedule for the GitHub job-logs coordinator (~2 min, SKIP overlap).

Registered in ``posthog/temporal/schedule.py`` via the product facade. The coordinator no-ops until
``OTLP_LOGS_INGEST_ENDPOINT`` is set, so registering the schedule is inert until the Logs sink exists.
"""

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

SCHEDULE_ID = "github-job-logs-coordinator-schedule"
SCHEDULE_INTERVAL = timedelta(minutes=2)


async def create_github_job_logs_coordinator_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "github-job-logs-coordinator",
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        # SKIP so a slow tick doesn't stack; the egress limiter (not cron frequency) caps spend.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
