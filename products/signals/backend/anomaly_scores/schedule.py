"""Schedule registration for the anomaly scoring tick."""

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

from products.signals.backend.anomaly_scores.tick import TICK_TIMEOUT, TICK_WORKFLOW_NAME, AnomalyScoringTickInput

ANOMALY_SCORING_TICK_SCHEDULE_ID = "anomaly-scoring-tick-schedule"
ANOMALY_SCORING_TICK_INTERVAL = timedelta(minutes=5)


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
    if await a_schedule_exists(client, ANOMALY_SCORING_TICK_SCHEDULE_ID):
        # Keep the live state, so a deploy does not resume a schedule that an operator paused.
        description = await client.get_schedule_handle(ANOMALY_SCORING_TICK_SCHEDULE_ID).describe()
        schedule.state = description.schedule.state
        await a_update_schedule(client, ANOMALY_SCORING_TICK_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, ANOMALY_SCORING_TICK_SCHEDULE_ID, schedule, trigger_immediately=False)
