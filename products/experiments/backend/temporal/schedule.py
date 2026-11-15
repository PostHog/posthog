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

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule

from products.experiments.backend.temporal.models import (
    CANARY_WORKFLOW_NAME,
    ENROLLMENT_CENSUS_WORKFLOW_NAME,
    SCHEDULED_RECALCULATION_WORKFLOW_NAME,
    ExperimentPrecomputeCanaryInputs,
    ExperimentPrecomputeEnrollmentCensusInputs,
)

CANARY_SCHEDULE_ID = "experiment-precompute-canary-schedule"
ENROLLMENT_CENSUS_SCHEDULE_ID = "experiment-precompute-enrollment-census-schedule"


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


async def create_experiment_precompute_enrollment_census_schedule(client: Client) -> None:
    """Daily report of teams that would qualify for precomputation enrollment. Report-only."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            ENROLLMENT_CENSUS_WORKFLOW_NAME,
            ExperimentPrecomputeEnrollmentCensusInputs(),
            id=f'{ENROLLMENT_CENSUS_SCHEDULE_ID}-{{{{.ScheduledTime.Format "2006-01-02"}}}}',
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 6 AM UTC",
                    hour=[ScheduleRange(start=6, end=6)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, ENROLLMENT_CENSUS_SCHEDULE_ID):
        await a_update_schedule(client, ENROLLMENT_CENSUS_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, ENROLLMENT_CENSUS_SCHEDULE_ID, schedule, trigger_immediately=False)


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
