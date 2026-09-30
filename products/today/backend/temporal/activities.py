"""Temporal activities. Each one only calls logic; payloads carry ids, never briefing content."""

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

import temporalio.activity
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team, User
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from ..facade.enums import BriefingStatus, BriefingTrigger
from ..logic import generate
from ..logic.briefings import create_briefing
from ..logic.eligibility import is_due, local_day
from ..models import DailyBriefing
from .inputs import (
    GENERATE_WORKFLOW_NAME,
    GenerateBriefingInputs,
    MarkFailedInputs,
    SchedulerInputs,
    generate_workflow_id,
)

# The schedule runs every 15 minutes, so each person falls into exactly one window before 8:00.
SCHEDULE_WINDOW_MINUTES = 15
ACTIVE_VIEWER_DAYS = 14
MAX_STARTS_PER_RUN = 500
STUCK_AFTER = timedelta(minutes=15)


@temporalio.activity.defn
async def collect_and_draft_activity(inputs: GenerateBriefingInputs) -> bool:
    return await database_sync_to_async(generate.collect_and_draft, thread_sensitive=False)(
        team_id=inputs.team_id, briefing_id=inputs.briefing_id
    )


@temporalio.activity.defn
async def write_and_check_activity(inputs: GenerateBriefingInputs) -> None:
    await database_sync_to_async(generate.write_and_check, thread_sensitive=False)(
        team_id=inputs.team_id, briefing_id=inputs.briefing_id
    )


@temporalio.activity.defn
async def mark_failed_activity(inputs: MarkFailedInputs) -> None:
    await database_sync_to_async(generate.mark_failed, thread_sensitive=False)(
        team_id=inputs.team_id, briefing_id=inputs.briefing_id, error=inputs.error
    )


def _fail_stuck_briefings(now: datetime) -> int:
    """Rows left in progress by a lost workflow; the page then falls back to their draft."""
    return (
        DailyBriefing.objects.unscoped()
        .filter(status__in=[BriefingStatus.COLLECTING, BriefingStatus.WRITING], created_at__lt=now - STUCK_AFTER)
        .update(status=BriefingStatus.FAILED, error="Generation did not finish in time.")
    )


def _due_briefings() -> list[DailyBriefing]:
    """Create the rows for people whose day starts in this window and who opened Today recently."""
    now = timezone.now()
    _fail_stuck_briefings(now)
    since = now - timedelta(days=ACTIVE_VIEWER_DAYS)
    # The scheduler is cross-team by design: it finds every recent viewer in every project.
    viewers = (
        DailyBriefing.objects.unscoped()
        .filter(last_viewed_at__gte=since)
        .order_by("team_id", "user_id", "-last_viewed_at")
        .distinct("team_id", "user_id")
        .values_list("team_id", "user_id", "timezone")
    )
    created: list[DailyBriefing] = []
    for team_id, user_id, timezone_name in viewers:
        if len(created) >= MAX_STARTS_PER_RUN:
            break
        if not is_due(now, timezone_name, SCHEDULE_WINDOW_MINUTES):
            continue
        day = local_day(now + timedelta(minutes=SCHEDULE_WINDOW_MINUTES), timezone_name)
        if DailyBriefing.objects.for_team(team_id).filter(user_id=user_id, local_day=day).exists():
            continue
        team = Team.objects.get(id=team_id)
        user = User.objects.filter(id=user_id, is_active=True).first()
        if user is None:
            continue
        created.append(
            create_briefing(
                team=team, user=user, day=day, timezone_name=timezone_name, trigger=BriefingTrigger.SCHEDULED
            )
        )
    return created


@temporalio.activity.defn
async def start_due_briefings_activity(inputs: SchedulerInputs) -> int:
    briefings = await database_sync_to_async(_due_briefings, thread_sensitive=False)()
    client = await async_connect()
    started = 0
    for briefing in briefings:
        try:
            await client.start_workflow(
                GENERATE_WORKFLOW_NAME,
                GenerateBriefingInputs(team_id=briefing.team_id, briefing_id=str(briefing.id)),
                id=generate_workflow_id(str(briefing.id)),
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            started += 1
        except WorkflowAlreadyStartedError:
            continue
    return started
