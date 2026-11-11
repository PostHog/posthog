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

from .reconcile_workflow import RECONCILE_WORKFLOW_NAME

SCHEDULE_ID = "knowledge-writer-merge-reconcile-schedule"
SCHEDULE_INTERVAL = timedelta(hours=1)


async def create_knowledge_writer_merge_reconcile_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            RECONCILE_WORKFLOW_NAME,
            id=SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL, offset=timedelta(minutes=17))],
            jitter=timedelta(minutes=5),
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
        return
    await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
