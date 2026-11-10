import datetime as dt

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

DAILY_FOCUS_SWEEP_SCHEDULE_ID = "slack-app-daily-focus-sweep-schedule"


async def create_slack_app_daily_focus_sweep_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "slack-app-daily-focus-sweep",
            id=DAILY_FOCUS_SWEEP_SCHEDULE_ID,
            task_queue=settings.TASKS_TASK_QUEUE,
            execution_timeout=dt.timedelta(minutes=5),
        ),
        spec=ScheduleSpec(cron_expressions=["*/5 * * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, DAILY_FOCUS_SWEEP_SCHEDULE_ID):
        await a_update_schedule(client, DAILY_FOCUS_SWEEP_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, DAILY_FOCUS_SWEEP_SCHEDULE_ID, schedule, trigger_immediately=False)
