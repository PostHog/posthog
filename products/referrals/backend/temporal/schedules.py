"""Temporal schedule registration for the referrals research flows.

Both schedules fire hourly. The next firing's look-back window is disjoint from the
previous one, so the same tweet should not surface twice on consecutive runs (modulo
schedule jitter, which is bounded to seconds). The internal flow CAN re-surface the same
PostHog users — dedup/skip logic is intentionally deferred.
"""

from dataclasses import asdict
from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.referrals.backend.temporal.activities import (
    InternalReferralResearchActivityInput,
    TwitterReferralResearchActivityInput,
)
from products.referrals.backend.temporal.constants import (
    INTERNAL_RESEARCH_SCHEDULE_ID,
    INTERNAL_RESEARCH_WORKFLOW_NAME,
    TWITTER_RESEARCH_SCHEDULE_ID,
    TWITTER_RESEARCH_WORKFLOW_NAME,
)


async def create_twitter_referral_research_schedule(client: Client) -> None:
    """Create or update the hourly Twitter referral research schedule."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            TWITTER_RESEARCH_WORKFLOW_NAME,
            asdict(TwitterReferralResearchActivityInput()),
            id=TWITTER_RESEARCH_SCHEDULE_ID,
            task_queue=settings.TASKS_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
    )
    if await a_schedule_exists(client, TWITTER_RESEARCH_SCHEDULE_ID):
        await a_update_schedule(client, TWITTER_RESEARCH_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, TWITTER_RESEARCH_SCHEDULE_ID, schedule, trigger_immediately=False)


async def create_internal_referral_research_schedule(client: Client) -> None:
    """Create or update the hourly internal-users referral research schedule."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            INTERNAL_RESEARCH_WORKFLOW_NAME,
            asdict(InternalReferralResearchActivityInput()),
            id=INTERNAL_RESEARCH_SCHEDULE_ID,
            task_queue=settings.TASKS_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
    )
    if await a_schedule_exists(client, INTERNAL_RESEARCH_SCHEDULE_ID):
        await a_update_schedule(client, INTERNAL_RESEARCH_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, INTERNAL_RESEARCH_SCHEDULE_ID, schedule, trigger_immediately=False)
