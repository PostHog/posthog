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

from products.error_tracking.backend.temporal.built_in_filters_refresh.types import BuiltInFiltersRefreshInputs
from products.error_tracking.backend.temporal.built_in_filters_refresh.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-built-in-filters-refresh-schedule"
# Rows only go stale when a deploy changes a definition, so an hourly sweep picks up a change soon after it ships.
SCHEDULE_INTERVAL = timedelta(hours=1)


async def create_error_tracking_built_in_filters_refresh_schedule(client: Client) -> None:
    built_in_filters_refresh_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            BuiltInFiltersRefreshInputs(),
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
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, built_in_filters_refresh_schedule, keep_paused=True)
    else:
        await a_create_schedule(client, SCHEDULE_ID, built_in_filters_refresh_schedule, trigger_immediately=False)
