"""Schedules a hog sets to wake itself later."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from django.utils import timezone

from croniter import croniter

from posthog.models.scoping import team_scope

from ..facade.enums import HogStatus, HogWakeCause
from ..models import Hog, HogSchedule
from . import runner

logger = logging.getLogger(__name__)

# A repeating schedule may not fire more often than this.
MIN_INTERVAL_SECONDS = 15 * 60
MAX_SCHEDULES_PER_HOG = 20


class ScheduleError(ValueError):
    pass


def _next_fire(cron_expression: str, after: datetime) -> datetime:
    return croniter(cron_expression, after).get_next(datetime).replace(tzinfo=UTC)


def create_schedule(hog: Hog, *, prompt: str, run_at: datetime | None, cron_expression: str | None) -> HogSchedule:
    if (run_at is None) == (cron_expression is None):
        raise ScheduleError("Set exactly one of run_at and cron_expression.")
    if hog.schedules.filter(enabled=True).count() >= MAX_SCHEDULES_PER_HOG:
        raise ScheduleError(f"A hog can have at most {MAX_SCHEDULES_PER_HOG} schedules.")
    now = timezone.now()
    if cron_expression is not None:
        if not croniter.is_valid(cron_expression) or len(cron_expression.split()) != 5:
            raise ScheduleError("cron_expression must be a valid 5-field cron expression.")
        first = _next_fire(cron_expression, now)
        if (_next_fire(cron_expression, first) - first).total_seconds() < MIN_INTERVAL_SECONDS:
            raise ScheduleError("A repeating schedule can fire at most every 15 minutes.")
        next_fire_at = first
    else:
        assert run_at is not None
        if run_at <= now:
            raise ScheduleError("run_at must be in the future.")
        next_fire_at = run_at
    return HogSchedule.objects.create(
        team_id=hog.team_id, hog=hog, prompt=prompt, cron_expression=cron_expression, next_fire_at=next_fire_at
    )


def list_schedules(hog: Hog) -> list[HogSchedule]:
    return list(hog.schedules.filter(enabled=True).order_by("next_fire_at"))


def delete_schedule(hog: Hog, schedule_id: UUID) -> bool:
    return bool(hog.schedules.filter(id=schedule_id, enabled=True).update(enabled=False))


def fire_due_schedules() -> int:
    """Wake every hog with a schedule that is due. Runs across teams from the beat task."""
    now = timezone.now()
    due = list(
        HogSchedule.objects.unscoped()
        .filter(enabled=True, next_fire_at__lte=now)
        .select_related("hog")
        .order_by("next_fire_at")[:200]
    )
    fired = 0
    for schedule in due:
        hog = schedule.hog
        schedule.last_fired_at = now
        if schedule.cron_expression:
            schedule.next_fire_at = _next_fire(schedule.cron_expression, now)
        else:
            schedule.enabled = False
            schedule.next_fire_at = None
        # Saved before the wake so a failing wake cannot fire the same schedule every minute.
        with team_scope(schedule.team_id):
            schedule.save(update_fields=["last_fired_at", "next_fire_at", "enabled"])
            if hog.deleted or hog.status == HogStatus.PAUSED:
                continue
            try:
                if runner.wake_hog(
                    hog,
                    trigger=f"A schedule you set has fired. Your note to yourself:\n\n{schedule.prompt}",
                    cause=HogWakeCause.SCHEDULE,
                ):
                    fired += 1
            except Exception:
                logger.exception("hog_schedule_fire_failed", extra={"schedule_id": str(schedule.id)})
    return fired
