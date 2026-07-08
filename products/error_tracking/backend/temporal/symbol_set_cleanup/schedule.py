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

from products.error_tracking.backend.temporal.symbol_set_cleanup.types import SymbolSetCleanupInputs
from products.error_tracking.backend.temporal.symbol_set_cleanup.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-symbol-set-cleanup-schedule"
SCHEDULE_INTERVAL = timedelta(hours=1)


async def create_error_tracking_symbol_set_cleanup_schedule(client: Client) -> None:
    symbol_set_cleanup_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            SymbolSetCleanupInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, symbol_set_cleanup_schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, symbol_set_cleanup_schedule, trigger_immediately=False)
