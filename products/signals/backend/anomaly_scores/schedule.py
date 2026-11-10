"""Schedule registration for the anomaly scoring tick and the due list refresh."""

from dataclasses import asdict
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

from products.signals.backend.anomaly_scores.refresh import REFRESH_TIMEOUT, REFRESH_WORKFLOW_NAME, DueListRefreshInput
from products.signals.backend.anomaly_scores.tick import TICK_TIMEOUT, TICK_WORKFLOW_NAME, AnomalyScoringTickInput

ANOMALY_SCORING_TICK_SCHEDULE_ID = "anomaly-scoring-tick-schedule"
ANOMALY_SCORING_TICK_INTERVAL = timedelta(minutes=5)
ANOMALY_SCORING_DUE_LIST_REFRESH_SCHEDULE_ID = "anomaly-scoring-due-list-refresh-schedule"
# Each run refreshes only the teams past their refresh window, so most runs end at once.
ANOMALY_SCORING_DUE_LIST_REFRESH_INTERVAL = timedelta(minutes=15)


async def _create_or_update(client: Client, schedule_id: str, schedule: Schedule) -> None:
    if await a_schedule_exists(client, schedule_id):
        # Keep the live state, so a deploy does not resume a schedule that an operator paused.
        description = await client.get_schedule_handle(schedule_id).describe()
        schedule.state = description.schedule.state
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)


async def create_anomaly_scoring_tick_schedule(client: Client) -> None:
    """Create or update the tick schedule on the self-driving task queue.

    The schedule exists in every environment. The `anomaly-scoring` flag gates the work, so turning
    the tick on or off needs no schedule change. SKIP on overlap: two ticks must not score the same
    insight at the same time, and a slow tick leaves the rest of the queue to the next one.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TICK_WORKFLOW_NAME,
            asdict(AnomalyScoringTickInput()),
            id=ANOMALY_SCORING_TICK_SCHEDULE_ID,
            task_queue=settings.SELF_DRIVING_TASK_QUEUE,
            execution_timeout=TICK_TIMEOUT,
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=ANOMALY_SCORING_TICK_INTERVAL,
                    offset=deterministic_offset(ANOMALY_SCORING_TICK_SCHEDULE_ID, ANOMALY_SCORING_TICK_INTERVAL),
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    await _create_or_update(client, ANOMALY_SCORING_TICK_SCHEDULE_ID, schedule)


async def create_anomaly_scoring_due_list_refresh_schedule(client: Client) -> None:
    """Create or update the due list refresh schedule on the self-driving task queue.

    The `due_list` field of the `anomaly-scoring` flag payload gates the work. SKIP on overlap: two runs
    must not refresh the same team at the same time.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            REFRESH_WORKFLOW_NAME,
            asdict(DueListRefreshInput()),
            id=ANOMALY_SCORING_DUE_LIST_REFRESH_SCHEDULE_ID,
            task_queue=settings.SELF_DRIVING_TASK_QUEUE,
            execution_timeout=REFRESH_TIMEOUT,
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=ANOMALY_SCORING_DUE_LIST_REFRESH_INTERVAL,
                    offset=deterministic_offset(
                        ANOMALY_SCORING_DUE_LIST_REFRESH_SCHEDULE_ID, ANOMALY_SCORING_DUE_LIST_REFRESH_INTERVAL
                    ),
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    await _create_or_update(client, ANOMALY_SCORING_DUE_LIST_REFRESH_SCHEDULE_ID, schedule)
