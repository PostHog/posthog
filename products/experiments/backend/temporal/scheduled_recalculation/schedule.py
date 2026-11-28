from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule

from products.experiments.backend.temporal.scheduled_recalculation.types import SCHEDULED_RECALCULATION_WORKFLOW_NAME

SCHEDULED_RECALCULATION_SCHEDULE_ID = "experiment-scheduled-recalculation"


async def create_experiment_scheduled_recalculation_schedules(client: Client) -> None:
    """Create or update the hourly schedule that starts a real metrics recalculation for every
    experiment eligible in the hour it fires.

    Fires at :30, after the daily timeseries schedule at :00, so the timeseries sync publish
    usually lands before a real run supersedes it. The workflow takes no input: discovery reads
    the hour and selects the teams configured for it, so one schedule serves all 24 hours.

    SKIP overlap: a run that outlives its hour must not stack on the next one.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SCHEDULED_RECALCULATION_WORKFLOW_NAME,
            id=f'{SCHEDULED_RECALCULATION_SCHEDULE_ID}-{{{{.ScheduledTime.Format "2006-01-02T15"}}}}',
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["30 * * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SCHEDULED_RECALCULATION_SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULED_RECALCULATION_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULED_RECALCULATION_SCHEDULE_ID, schedule, trigger_immediately=False)


async def delete_experiment_scheduled_recalculation_schedules(client: Client) -> None:
    """Delete the scheduled recalculation schedule."""
    try:
        await a_delete_schedule(client, SCHEDULED_RECALCULATION_SCHEDULE_ID)
    except Exception:
        pass  # Schedule might not exist
