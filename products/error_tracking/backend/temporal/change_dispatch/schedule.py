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

from products.error_tracking.backend.temporal.change_dispatch.types import ChangeDispatchInputs
from products.error_tracking.backend.temporal.change_dispatch.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-issue-change-dispatch-schedule"
SCHEDULE_INTERVAL = timedelta(minutes=1)
# Each run drains the whole outbox, so a missed run never needs replaying.
SCHEDULE_CATCHUP_WINDOW = timedelta(minutes=1)


async def create_error_tracking_issue_change_dispatch_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            ChangeDispatchInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=SCHEDULE_INTERVAL, offset=deterministic_offset(SCHEDULE_ID, SCHEDULE_INTERVAL)
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_CATCHUP_WINDOW),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
