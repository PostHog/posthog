"""Schedule registration for the inbox ranking scoring sweep."""

from __future__ import annotations

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
    """Create or update the sweep schedule on the signals task queue (shared with the rest of the
    signals worker). SKIP on overlap: a slow tick just means the next one picks up the remainder,
    and two sweeps scoring the same batch would only duplicate rows in the log."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SCORING_WORKFLOW_NAME,
            asdict(ScoreInboxReportsInput()),
            id=INBOX_RANKING_SCORING_SCHEDULE_ID,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=settings.SIGNALS_RANKING_SWEEP_INTERVAL_MINUTES))]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, INBOX_RANKING_SCORING_SCHEDULE_ID):
        await a_update_schedule(client, INBOX_RANKING_SCORING_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, INBOX_RANKING_SCORING_SCHEDULE_ID, schedule, trigger_immediately=False)
