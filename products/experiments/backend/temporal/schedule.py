from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.experiments.backend.temporal.models import CANARY_WORKFLOW_NAME, ExperimentPrecomputeCanaryInputs

CANARY_SCHEDULE_ID = "experiment-precompute-canary-schedule"


async def create_experiment_precompute_canary_schedule(client: Client) -> None:
    """Daily off-peak run of the experiment precompute canary. SKIP overlap: a slow run (the per-run time
    budget allows up to an hour of queries) must not stack on the next day's."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CANARY_WORKFLOW_NAME,
            ExperimentPrecomputeCanaryInputs(),
            id=f'{CANARY_SCHEDULE_ID}-{{{{.ScheduledTime.Format "2006-01-02"}}}}',
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 3 AM UTC",
                    hour=[ScheduleRange(start=3, end=3)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, CANARY_SCHEDULE_ID):
        await a_update_schedule(client, CANARY_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, CANARY_SCHEDULE_ID, schedule, trigger_immediately=False)
