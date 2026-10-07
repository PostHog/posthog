import datetime as dt

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from .contracts import WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME, WarehouseSuggestionsInputs

WAREHOUSE_SUGGESTIONS_SCHEDULE_ID = "warehouse-suggestions-schedule"
CRON_AFTER_THE_DAILY_ROLLUP = "30 8 * * *"
PAUSED_ON_CREATE_NOTE = "Created paused. Resume once the warehouse object reads rollup is backfilled."


async def create_warehouse_suggestions_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WAREHOUSE_SUGGESTIONS_WORKFLOW_NAME,
            WarehouseSuggestionsInputs(),
            id=WAREHOUSE_SUGGESTIONS_SCHEDULE_ID,
            task_queue=settings.DATA_MODELING_TASK_QUEUE,
            execution_timeout=dt.timedelta(hours=3),
        ),
        spec=ScheduleSpec(cron_expressions=[CRON_AFTER_THE_DAILY_ROLLUP]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, WAREHOUSE_SUGGESTIONS_SCHEDULE_ID):
        await a_update_schedule(client, WAREHOUSE_SUGGESTIONS_SCHEDULE_ID, schedule, keep_paused=True)
        return
    schedule.state = ScheduleState(paused=True, note=PAUSED_ON_CREATE_NOTE)
    await a_create_schedule(client, WAREHOUSE_SUGGESTIONS_SCHEDULE_ID, schedule, trigger_immediately=False)
