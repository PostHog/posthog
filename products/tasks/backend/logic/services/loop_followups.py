"""Self-defer for Slack follow-up loops: a fired run pushing its own re-check to a later time.

A loop-fired run cannot re-arm its loop through the loops API (`loop:write` is stripped from
run tokens, see access.LOOP_FIRED_RUN_EXCLUDED_SCOPES), so the sandbox calls the run-scoped
`defer_followup` endpoint and the re-arm happens here, server-side. Spent one-time triggers
are terminal by design (loop_service.complete_one_time_trigger), so a defer creates a fresh
one-time trigger on the same loop rather than reusing the fired one.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.utils import timezone as django_timezone

from products.tasks.backend.exceptions import FollowupDeferError
from products.tasks.backend.logic.services.loop_runs import (
    SLACK_FOLLOWUP_MAX_DEFERS_DEFAULT,
    slack_thread_context_from_target,
)
from products.tasks.backend.loop_service import sync_loop_trigger_schedule
from products.tasks.backend.models import Loop, LoopTrigger, TaskRun

logger = logging.getLogger(__name__)

FOLLOWUP_DEFER_MIN_DELAY = timedelta(hours=1)
FOLLOWUP_DEFER_MAX_DELAY = timedelta(days=90)


@dataclass(frozen=True, kw_only=True)
class FollowupDeferResult:
    scheduled_for: datetime
    defers_used: int
    max_defers: int


def request_followup_defer(task_run: TaskRun, *, until: datetime, reason: str = "") -> FollowupDeferResult:
    """Re-arm a thread-bound follow-up loop to check again at `until` instead of reporting now.

    Called on behalf of the fired run's agent when the data isn't mature enough for a useful
    report. Bounded to [1 hour, 90 days] out, capped per loop (`slack_thread_target.max_defers`),
    and limited to one pending re-check at a time, so a confused agent can't schedule an
    unbounded tail of runs.
    """
    state = task_run.state if isinstance(task_run.state, dict) else {}
    loop_id = state.get("loop_id")

    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    now = django_timezone.now()
    if not (now + FOLLOWUP_DEFER_MIN_DELAY <= until <= now + FOLLOWUP_DEFER_MAX_DELAY):
        raise FollowupDeferError("invalid_until", "The re-check time must be between 1 hour and 90 days from now.")

    with transaction.atomic():
        # The loop row lock serializes concurrent defer calls for the same loop, so two racing
        # requests can't both pass the pending-trigger check and schedule two re-checks.
        loop = (
            Loop.objects.for_team(task_run.team_id, canonical=True).select_for_update().filter(id=loop_id).first()
            if loop_id
            else None
        )
        target = loop.slack_thread_target if loop is not None and isinstance(loop.slack_thread_target, dict) else {}
        if loop is None or slack_thread_context_from_target(target) is None:
            raise FollowupDeferError("not_a_followup", "Only a Slack follow-up loop's run can defer its check.")

        one_time_triggers = LoopTrigger.objects.for_team(task_run.team_id, canonical=True).filter(
            loop=loop, type=LoopTrigger.TriggerType.SCHEDULE, config__has_key="run_at"
        )
        if one_time_triggers.filter(completed_at__isnull=True, enabled=True).exists():
            raise FollowupDeferError("already_scheduled", "A re-check is already scheduled for this follow-up.")

        max_defers = _coerce_max_defers(target)
        # The first one-time trigger was the original ask; every completed one beyond it was a defer.
        defers_used = max(one_time_triggers.filter(completed_at__isnull=False).count() - 1, 0)
        if defers_used >= max_defers:
            raise FollowupDeferError(
                "limit_reached",
                f"This follow-up has already been deferred {max_defers} times. Report with the data available.",
            )

        # Direct instantiation, not the manager's create(): callers include Temporal-adjacent
        # contexts with no ambient team scope, where the fail-closed manager would raise.
        trigger = LoopTrigger(
            team_id=loop.team_id,
            loop=loop,
            type=LoopTrigger.TriggerType.SCHEDULE,
            enabled=True,
            config={
                "run_at": until.astimezone(UTC).isoformat(),
                # Provenance for the loop's history; build_loop_trigger_schedule ignores extra keys.
                "defer_reason": reason[:500],
                "deferred_from_run_id": str(task_run.id),
            },
            schedule_sync_status=LoopTrigger.ScheduleSyncStatus.PENDING,
        )
        trigger.save()

    # Sync after commit, like every other trigger-sync site: a rollback must not leave a live
    # Temporal schedule pointing at a trigger row that never landed.
    sync_loop_trigger_schedule(trigger)

    logger.info(
        "loop_followup_deferred",
        extra={
            "loop_id": str(loop.id),
            "task_run_id": str(task_run.id),
            "scheduled_for": until.isoformat(),
            "defers_used": defers_used + 1,
        },
    )
    return FollowupDeferResult(scheduled_for=until, defers_used=defers_used + 1, max_defers=max_defers)


def _coerce_max_defers(target: dict) -> int:
    try:
        return max(int(target.get("max_defers", SLACK_FOLLOWUP_MAX_DEFERS_DEFAULT)), 0)
    except (TypeError, ValueError):
        return SLACK_FOLLOWUP_MAX_DEFERS_DEFAULT
