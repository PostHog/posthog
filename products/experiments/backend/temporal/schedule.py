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
    ScheduledRecalculationWorkflowInputs,
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


SCHEDULED_RECALCULATION_SCHEDULE_ID_PREFIX = "experiment-scheduled-recalculation-hour"


async def create_experiment_scheduled_recalculation_schedules(client: Client) -> None:
    """Create or update 24 schedules, one per hour, that start a real metrics recalculation for
    every eligible experiment belonging to teams configured for that hour.

    Each fires at :30, after the daily timeseries schedule at :00, so the timeseries sync publish
    usually lands before a real run supersedes it. 24 separate schedules rather than one hourly
    schedule, matching the timeseries workflows: a run longer than an hour cannot overlap itself,
    so no overlap policy is needed.
    """
    for hour in range(24):
        schedule_id = f"{SCHEDULED_RECALCULATION_SCHEDULE_ID_PREFIX}-{hour:02d}"

        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                SCHEDULED_RECALCULATION_WORKFLOW_NAME,
                ScheduledRecalculationWorkflowInputs(hour=hour),
                id=f'{SCHEDULED_RECALCULATION_SCHEDULE_ID_PREFIX}-{hour:02d}-{{{{.ScheduledTime.Format "2006-01-02"}}}}',
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[f"30 {hour} * * *"]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        )

        if await a_schedule_exists(client, schedule_id):
            await a_update_schedule(client, schedule_id, schedule)
        else:
            await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)


async def delete_experiment_scheduled_recalculation_schedules(client: Client) -> None:
    """Delete all 24 scheduled recalculation schedules."""
    for hour in range(24):
        try:
            await a_delete_schedule(client, f"{SCHEDULED_RECALCULATION_SCHEDULE_ID_PREFIX}-{hour:02d}")
        except Exception:
            pass  # Schedule might not exist
