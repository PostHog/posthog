"""Temporal schedule for the engineering-analytics CI-signals coordinator (hourly, SKIP overlap).

Registered in ``posthog/temporal/schedule.py`` via the product facade. The coordinator no-ops for
teams that haven't enabled the engineering_analytics signal source, so registering the schedule is
inert until a team opts in.
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

SCHEDULE_ID = "engineering-analytics-ci-signals-coordinator-schedule"
SCHEDULE_INTERVAL = timedelta(hours=1)


async def create_ci_signals_coordinator_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "engineering-analytics-ci-signals-coordinator",
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            # Bounded to the interval so a wedged sweep can never block more than one SKIP tick.
            execution_timeout=SCHEDULE_INTERVAL,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        # SKIP so a slow tick doesn't stack; enrolment (not cron frequency) bounds the work.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
