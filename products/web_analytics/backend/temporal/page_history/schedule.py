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

from products.web_analytics.backend.temporal.page_history.types import (
    TICK_INTERVAL,
    TICK_SCHEDULE_ID,
    TICK_WORKFLOW_NAME,
    TickInputs,
)


async def create_heatmap_page_history_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TICK_WORKFLOW_NAME,
            TickInputs(),
            id=TICK_SCHEDULE_ID,
            task_queue=settings.WEB_ANALYTICS_TASK_QUEUE,
            execution_timeout=timedelta(minutes=10),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=TICK_INTERVAL)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, TICK_SCHEDULE_ID):
        await a_update_schedule(client, TICK_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, TICK_SCHEDULE_ID, schedule, trigger_immediately=False)
