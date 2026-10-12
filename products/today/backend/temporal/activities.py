"""Temporal activities. Each one only calls logic. Payloads carry ids only."""

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

import temporalio.activity
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team, User
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater

from ..facade.enums import BriefingStatus, BriefingTrigger
from ..feature_flags import may_get_briefing
from ..logic import generate
from ..logic.briefings import create_briefing
from ..logic.eligibility import due_day
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
# Someone who has not opened Today for a week gets the report list until they come back; no briefing is written for them.
ACTIVE_VIEWER_DAYS = 7
MAX_STARTS_PER_RUN = 500
# Longer than the run's budget, so a sweep never fails a run that is still inside it.
STUCK_AFTER = generate.RUN_TIMEOUT + timedelta(minutes=5)


# The activity type name is in the history of every generate workflow. A new name makes the
# replay of a workflow that is in flight during a deploy fail with a non-determinism error.
@temporalio.activity.defn(name="run_agent_activity")
async def write_briefing_activity(inputs: GenerateBriefingInputs) -> None:
    async with Heartbeater():
        await generate.write_briefing(team_id=inputs.team_id, briefing_id=inputs.briefing_id)


@temporalio.activity.defn
async def mark_failed_activity(inputs: MarkFailedInputs) -> None:
    await database_sync_to_async(generate.mark_failed, thread_sensitive=False)(
        team_id=inputs.team_id, briefing_id=inputs.briefing_id, error=inputs.error
    )


def _fail_stuck_briefings(now: datetime) -> int:
    """Rows left in progress by a lost workflow, so the page stops waiting for them."""
    return (
        DailyBriefing.objects.unscoped()
        .filter(status__in=[BriefingStatus.COLLECTING, BriefingStatus.WRITING], created_at__lt=now - STUCK_AFTER)
        .update(status=BriefingStatus.FAILED, error="Generation did not finish in time.")
    )


def _due_briefings() -> list[DailyBriefing]:
    """The scheduled rows to start for people whose briefing day starts in this window and who opened Today recently.

    Rows are created first and their workflows started afterwards, so a start that fails leaves a
    row behind; it is returned again on the next tick, until its workflow exists or the stuck sweep
    fails it.
    """
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
        (team_id, user_id, timezone_name, day)
        for team_id, user_id, timezone_name in viewers
        if (day := due_day(now, timezone_name, SCHEDULE_WINDOW_MINUTES)) is not None
    ]
    if not due:
        return []
    team_ids = {team_id for team_id, _, _, _ in due}
    user_ids = {user_id for _, user_id, _, _ in due}
    teams = Team.objects.in_bulk(team_ids)
    users = User.objects.filter(is_active=True).in_bulk(user_ids)
    due_rows = DailyBriefing.objects.unscoped().filter(
        team_id__in=team_ids, user_id__in=user_ids, local_day__in={day for _, _, _, day in due}
    )
    existing = set(due_rows.values_list("team_id", "user_id", "local_day"))
    created = 0
    for team_id, user_id, timezone_name, day in due:
        if created >= MAX_STARTS_PER_RUN:
            break
        team, user = teams.get(team_id), users.get(user_id)
        if (team_id, user_id, day) in existing or team is None or user is None or not may_get_briefing(user, team):
            continue
        # None when the person opened Today themselves since the rows were read.
        if create_briefing(
            team=team, user=user, local_day=day, timezone_name=timezone_name, trigger=BriefingTrigger.SCHEDULED
        ):
            created += 1
    return list(due_rows.filter(trigger=BriefingTrigger.SCHEDULED, status=BriefingStatus.COLLECTING))


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
