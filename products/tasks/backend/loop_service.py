import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime

from celery.exceptions import SoftTimeLimitExceeded
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleState,
)

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import (
    create_schedule,
    delete_schedule,
    pause_schedule,
    schedule_exists,
    unpause_schedule,
    update_schedule,
)

from .models import Loop, LoopTrigger

logger = logging.getLogger(__name__)

LOOP_SCHEDULE_CATCHUP_WINDOW = timedelta(minutes=5)


def _run_at_datetime(raw: str) -> datetime:
    parsed = parse_datetime(raw)
    if parsed is None:
        raise ValueError(f"Invalid run_at value: {raw!r}")
    if django_timezone.is_naive(parsed):
        parsed = django_timezone.make_aware(parsed, UTC)
    return parsed.astimezone(UTC)


def _one_time_schedule_spec(run_at: datetime) -> ScheduleSpec:
    # A single calendar match: pinning every field including year narrows the match
    # to this exact instant, and remaining_actions=1 on the schedule state stops it
    # from firing again if the calendar expression were ever re-evaluated.
    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                second=[ScheduleRange(run_at.second)],
                minute=[ScheduleRange(run_at.minute)],
                hour=[ScheduleRange(run_at.hour)],
                day_of_month=[ScheduleRange(run_at.day)],
                month=[ScheduleRange(run_at.month)],
                year=[ScheduleRange(run_at.year)],
            )
        ],
        time_zone_name="UTC",
    )


def build_loop_trigger_schedule(trigger: LoopTrigger) -> Schedule:
    """Build the Temporal Schedule for a schedule-type loop trigger.

    Explicit policy throughout, never the SDK default: overlap SKIP and a 5 minute
    catchup window, so a Temporal outage never replays its whole missed window as a
    burst on recovery. A `run_at` in the trigger config produces a one-time schedule
    (limited_actions, remaining_actions=1); otherwise it's a recurring cron schedule.
    """
    config = trigger.config or {}
    action = ScheduleActionStartWorkflow(
        "run-loop",
        str(trigger.id),
        id=f'loop-trigger-{trigger.id}-{{{{.ScheduledTime.Format "2006-01-02-15-04-05"}}}}',
        task_queue=settings.TASKS_TASK_QUEUE,
    )
    is_enabled = trigger.enabled and trigger.loop.enabled

    run_at = config.get("run_at")
    if run_at:
        spec = _one_time_schedule_spec(_run_at_datetime(run_at))
        state = ScheduleState(
            paused=not is_enabled,
            limited_actions=True,
            remaining_actions=1,
            note=f"One-time schedule for loop trigger: {trigger.id}",
        )
    else:
        spec = ScheduleSpec(
            cron_expressions=[config["cron_expression"]],
            time_zone_name=config.get("timezone", "UTC"),
        )
        state = ScheduleState(
            paused=not is_enabled,
            note=f"Schedule for loop trigger: {trigger.id}",
        )

    return Schedule(
        action=action,
        spec=spec,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=LOOP_SCHEDULE_CATCHUP_WINDOW),
        state=state,
    )


def sync_loop_trigger_schedule(trigger: LoopTrigger) -> None:
    """Create or update the Temporal Schedule backing a schedule-type loop trigger.

    Never lets a Temporal error propagate to the caller: failures are logged and
    recorded on `trigger.schedule_sync_status` instead, per the Lifecycle section of
    products/tasks/docs/LOOPS.md.
    """
    if trigger.type != LoopTrigger.TriggerType.SCHEDULE:
        return

    if trigger.completed_at is not None:
        # A spent one-time trigger is terminal. Whatever path re-syncs it (reconciliation, a later
        # loop edit that resets it to `pending`), make sure no live Schedule lingers and never
        # create a new one. This single guard is why no path can resurrect a one-time schedule.
        delete_loop_trigger_schedule(trigger)
        LoopTrigger.objects.for_team(trigger.team_id, canonical=True).filter(id=trigger.id).update(
            schedule_sync_status=LoopTrigger.ScheduleSyncStatus.SYNCED
        )
        return

    try:
        temporal = sync_connect()
        schedule = build_loop_trigger_schedule(trigger)
        if schedule_exists(temporal, trigger.schedule_id):
            update_schedule(temporal, trigger.schedule_id, schedule)
            if trigger.enabled and trigger.loop.enabled:
                unpause_schedule(temporal, trigger.schedule_id, note="Loop trigger enabled")
            else:
                pause_schedule(temporal, trigger.schedule_id, note="Loop trigger paused")
        else:
            create_schedule(temporal, trigger.schedule_id, schedule)
        status = LoopTrigger.ScheduleSyncStatus.SYNCED
    except SoftTimeLimitExceeded:
        # The reconciliation sweep runs this in a loop under a Celery soft time limit; let the limit
        # unwind the task instead of misrecording a timeout as a per-trigger Temporal sync failure.
        raise
    except Exception:
        logger.exception("loop_trigger_schedule_sync_failed", extra={"loop_trigger_id": str(trigger.id)})
        status = LoopTrigger.ScheduleSyncStatus.FAILED

    LoopTrigger.objects.for_team(trigger.team_id, canonical=True).filter(id=trigger.id).update(
        schedule_sync_status=status
    )


def delete_loop_trigger_schedule(trigger: LoopTrigger) -> None:
    """Delete the Temporal Schedule for a trigger. Idempotent: swallows not-found and Temporal errors.

    Deliberately keys off `schedule_id`/`schedule_exists`, not `trigger.type`: a trigger whose
    type was just changed away from `schedule` still has a live Schedule to tear down, and a
    non-schedule trigger simply has no Schedule to find, so this is safe to call for any type.
    """
    try:
        temporal = sync_connect()
        if schedule_exists(temporal, trigger.schedule_id):
            delete_schedule(temporal, trigger.schedule_id)
    except Exception:
        logger.exception("loop_trigger_schedule_delete_failed", extra={"loop_trigger_id": str(trigger.id)})


def complete_one_time_trigger(trigger: LoopTrigger) -> None:
    """Finalize a one-time (`run_at`) trigger after its single fire.

    Temporal never garbage-collects a schedule whose `remaining_actions` reached 0, so the spent
    Schedule lingers and keeps a dead row registered unless we delete it. Stamping `completed_at`
    makes the terminal state explicit, so the trigger never reads as active and the sync guard in
    `sync_loop_trigger_schedule` refuses to re-arm it. Idempotent: only the first call stamps the
    timestamp, and the Temporal delete is a no-op when the Schedule is already gone.
    """
    delete_loop_trigger_schedule(trigger)
    LoopTrigger.objects.for_team(trigger.team_id, canonical=True).filter(
        id=trigger.id, completed_at__isnull=True
    ).update(completed_at=django_timezone.now(), schedule_sync_status=LoopTrigger.ScheduleSyncStatus.SYNCED)


def pause_loop_schedules(loop: Loop) -> None:
    """Pause every schedule-backed trigger's Temporal Schedule for a loop.

    Best-effort per trigger: one trigger's Temporal failure doesn't stop the rest
    from being paused.
    """
    triggers = list(
        LoopTrigger.objects.for_team(loop.team_id, canonical=True).filter(
            loop=loop, type=LoopTrigger.TriggerType.SCHEDULE
        )
    )
    if not triggers:
        return
    try:
        temporal = sync_connect()
    except Exception:
        logger.exception("loop_schedule_pause_failed", extra={"loop_id": str(loop.id)})
        return
    for trigger in triggers:
        try:
            if schedule_exists(temporal, trigger.schedule_id):
                pause_schedule(temporal, trigger.schedule_id, note="Loop paused")
        except Exception:
            logger.exception("loop_schedule_pause_failed", extra={"loop_trigger_id": str(trigger.id)})


def delete_loop_schedules(loop: Loop) -> None:
    """Delete every schedule-backed trigger's Temporal Schedule for a loop.

    Used when a loop is deleted, where the loop is gone for good, unlike `pause_loop_schedules`,
    which is reversible on re-enable. A soft-delete that only paused would leave the Schedule
    registered in Temporal forever. Best-effort per trigger.
    """
    triggers = list(
        LoopTrigger.objects.for_team(loop.team_id, canonical=True).filter(
            loop=loop, type=LoopTrigger.TriggerType.SCHEDULE
        )
    )
    if not triggers:
        return
    try:
        temporal = sync_connect()
    except Exception:
        logger.exception("loop_schedule_delete_failed", extra={"loop_id": str(loop.id)})
        return
    for trigger in triggers:
        try:
            if schedule_exists(temporal, trigger.schedule_id):
                delete_schedule(temporal, trigger.schedule_id)
        except Exception:
            logger.exception("loop_schedule_delete_failed", extra={"loop_trigger_id": str(trigger.id)})


def delete_schedules_for_team(team_id: int) -> None:
    """Delete every schedule-backed loop trigger's Temporal Schedule for a team.

    For team/org/project deletion: Django's CASCADE removes the LoopTrigger rows but never talks
    to Temporal, so without this the Schedules keep firing forever into deleted triggers. Called
    from the team-deletion workflow before the rows are cascaded away. Best-effort per trigger.
    """
    triggers = list(LoopTrigger.objects.for_team(team_id, canonical=True).filter(type=LoopTrigger.TriggerType.SCHEDULE))
    if not triggers:
        return
    try:
        temporal = sync_connect()
    except Exception:
        logger.exception("loop_schedule_delete_failed", extra={"team_id": team_id})
        return
    for trigger in triggers:
        try:
            if schedule_exists(temporal, trigger.schedule_id):
                delete_schedule(temporal, trigger.schedule_id)
        except Exception:
            logger.exception("loop_schedule_delete_failed", extra={"loop_trigger_id": str(trigger.id)})


def signal_loop_run_cancelled(workflow_id: str) -> None:
    """Best-effort: tell a displaced loop run's workflow to wind down its sandbox.

    The run's DB row is already CANCELLED; this signals the live workflow so the sandbox
    stops instead of running to completion under the loop owner's credentials. Mirrors
    `facade.api.signal_workflow_completion`, kept here so the logic layer never imports the
    facade. Swallows errors: a missing/finished workflow just means nothing to stop.
    """
    import asyncio  # noqa: PLC0415 — only needed when signalling

    from products.tasks.backend.temporal.process_task.workflow import (  # noqa: PLC0415 — keep temporalio off the module import path
        ProcessTaskWorkflow,
    )

    try:
        client = sync_connect()
        handle = client.get_workflow_handle(workflow_id)
        asyncio.run(
            handle.signal(ProcessTaskWorkflow.complete_task, args=["cancelled", "Superseded by a newer loop run"])
        )
    except Exception:
        logger.exception("loop_run_cancel_signal_failed", extra={"workflow_id": workflow_id})


def resume_loop_schedules(loop: Loop) -> None:
    """Unpause (or recreate, if missing) every enabled schedule trigger's Temporal Schedule."""
    triggers = list(
        LoopTrigger.objects.for_team(loop.team_id, canonical=True).filter(
            loop=loop, type=LoopTrigger.TriggerType.SCHEDULE, enabled=True
        )
    )
    if not triggers:
        return
    try:
        temporal = sync_connect()
    except Exception:
        logger.exception("loop_schedule_resume_failed", extra={"loop_id": str(loop.id)})
        return
    for trigger in triggers:
        try:
            if schedule_exists(temporal, trigger.schedule_id):
                unpause_schedule(temporal, trigger.schedule_id, note="Loop resumed")
            else:
                sync_loop_trigger_schedule(trigger)
        except Exception:
            logger.exception("loop_schedule_resume_failed", extra={"loop_trigger_id": str(trigger.id)})
