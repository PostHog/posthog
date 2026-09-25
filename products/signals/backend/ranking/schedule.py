"""Schedule registration for the inbox ranking scoring sweep."""

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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.signals.backend.ranking.sweep import SCORING_WORKFLOW_NAME, ScoreInboxReportsInput

INBOX_RANKING_SCORING_SCHEDULE_ID = "inbox-ranking-scoring-sweep-schedule"


async def create_inbox_ranking_scoring_schedule(client: Client) -> None:
    """Create or update the sweep schedule on the signals task queue.

    The schedule exists in every environment. `INBOX_RANKING_SCORING_ENABLED` gates the work, so
    turning the sweep on or off needs no schedule change. SKIP on overlap: a slow tick leaves the
    rest to the next one, and two sweeps must not score the same batch at the same time.
    """
    interval = timedelta(minutes=settings.INBOX_RANKING_SCORING_INTERVAL_MINUTES)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SCORING_WORKFLOW_NAME,
            asdict(ScoreInboxReportsInput()),
            id=INBOX_RANKING_SCORING_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=interval,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, INBOX_RANKING_SCORING_SCHEDULE_ID):
        await a_update_schedule(client, INBOX_RANKING_SCORING_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, INBOX_RANKING_SCORING_SCHEDULE_ID, schedule, trigger_immediately=False)
