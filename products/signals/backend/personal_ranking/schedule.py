"""Schedule registration for the personal inbox ranking tick."""

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

from products.signals.backend.personal_ranking.tick import TICK_WORKFLOW_NAME, PersonalRankingTickInput

PERSONAL_INBOX_RANKING_TICK_SCHEDULE_ID = "personal-inbox-ranking-tick-schedule"


async def create_personal_inbox_ranking_tick_schedule(client: Client) -> None:
    """Create or update the tick schedule on the self-driving task queue.

    The schedule exists in every environment. The `tick` object of the `personal-inbox-ranking` flag
    payload gates the work, so turning the tick on or off needs no schedule change. SKIP on overlap: a slow
    tick leaves the rest of the due pairs to the next one.
    """
    interval = timedelta(minutes=settings.PERSONAL_INBOX_RANKING_TICK_INTERVAL_MINUTES)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TICK_WORKFLOW_NAME,
            asdict(PersonalRankingTickInput()),
            id=PERSONAL_INBOX_RANKING_TICK_SCHEDULE_ID,
            task_queue=settings.SELF_DRIVING_TASK_QUEUE,
            execution_timeout=interval,
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=interval, offset=deterministic_offset(PERSONAL_INBOX_RANKING_TICK_SCHEDULE_ID, interval)
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, PERSONAL_INBOX_RANKING_TICK_SCHEDULE_ID):
        # Keep the live state, so a deploy does not resume a schedule that an operator paused.
        description = await client.get_schedule_handle(PERSONAL_INBOX_RANKING_TICK_SCHEDULE_ID).describe()
        schedule.state = description.schedule.state
        await a_update_schedule(client, PERSONAL_INBOX_RANKING_TICK_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, PERSONAL_INBOX_RANKING_TICK_SCHEDULE_ID, schedule, trigger_immediately=False)
