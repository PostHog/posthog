"""Temporal schedule for the GitHub job-logs coordinator (~2 min, SKIP overlap).

NOT yet registered in ``posthog/temporal/schedule.py`` — see ``coordinator.py`` for why (the
``github_workflow_jobs`` metadata source has to land first). To wire it live, import
``create_github_job_logs_coordinator_schedule`` there and append it to the ``schedules`` list.
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
        # The egress limiter, not the cron, caps GitHub spend — a frequent drain over a throttled
        # queue is cheap. SKIP so a slow tick doesn't stack.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
