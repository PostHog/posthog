"""Temporal activities. Each one only calls logic.

Payloads carry ids, except the source results: short titles and scalar facts, never text written by customers.
"""

from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

import temporalio.activity
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team, User
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from ..facade.enums import BriefingStatus, BriefingTrigger
from ..feature_flags import is_enabled_for
from ..logic import generate
from ..logic.briefings import create_briefing
from ..logic.candidates import Candidate
from ..logic.eligibility import is_due, local_day
from ..models import DailyBriefing
from .inputs import (
    GENERATE_WORKFLOW_NAME,
    CollectSourceInputs,
    DraftInputs,
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
async def collect_source_activity(inputs: CollectSourceInputs) -> list[dict[str, Any]]:
    candidates = await database_sync_to_async(generate.collect_source, thread_sensitive=False)(
        team_id=inputs.team_id, briefing_id=inputs.briefing_id, source=inputs.source
    )
    return [candidate.to_payload() for candidate in candidates]


@temporalio.activity.defn
async def draft_activity(inputs: DraftInputs) -> bool:
    return await database_sync_to_async(generate.draft_briefing, thread_sensitive=False)(
        team_id=inputs.team_id,
        briefing_id=inputs.briefing_id,
        candidates=[Candidate.from_payload(payload) for payload in inputs.candidates],
        failed_sources=list(inputs.failed_sources),
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
    due = [
        (team_id, user_id, timezone_name, local_day(now + timedelta(minutes=SCHEDULE_WINDOW_MINUTES), timezone_name))
        for team_id, user_id, timezone_name in viewers
        if is_due(now, timezone_name, SCHEDULE_WINDOW_MINUTES)
    ]
    if not due:
        return []
    team_ids = {team_id for team_id, _, _, _ in due}
    user_ids = {user_id for _, user_id, _, _ in due}
    teams = Team.objects.in_bulk(team_ids)
    users = User.objects.filter(is_active=True).in_bulk(user_ids)
    existing = set(
        DailyBriefing.objects.unscoped()
        .filter(team_id__in=team_ids, user_id__in=user_ids, local_day__in={day for _, _, _, day in due})
        .values_list("team_id", "user_id", "local_day")
    )
    created: list[DailyBriefing] = []
    for team_id, user_id, timezone_name, day in due:
        if len(created) >= MAX_STARTS_PER_RUN:
            break
        team, user = teams.get(team_id), users.get(user_id)
        # Someone who opened Today may have lost the flag since. They get no row and no workflow.
        if (team_id, user_id, day) in existing or team is None or user is None or not is_enabled_for(user, team):
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
