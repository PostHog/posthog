"""Wakes a hog by starting, or continuing, a task run for it."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from posthog.models import Team

from products.tasks.backend.facade import api as tasks_facade

from ..facade.enums import HogMessageAuthor, HogWakeCause
from ..models import Hog, HogMessage, HogWake
from ..task_profiles import HOG
from .prompt import build_wake_prompt

logger = logging.getLogger(__name__)

# A hog that never calls hog-done stops showing as working after this long.
WORKING_TIMEOUT = timedelta(minutes=30)
# Wakes the owner did not cause themselves, per hog, in any rolling hour.
MAX_AUTOMATIC_WAKES_PER_HOUR = 60
# How many hog-to-hog notes may chain before the last one is refused.
MAX_HOPS = 4


class WakeRefused(Exception):
    """A limit stopped the wake. The message says which one, in words the caller can show."""


def _within_hourly_cap(hog: Hog, cause: HogWakeCause, hops: int) -> bool:
    """The owner's own messages always get through. Everything else shares one hourly budget."""
    if cause == HogWakeCause.USER:
        return True
    recent = HogWake.objects.filter(hog=hog, created_at__gte=timezone.now() - timedelta(hours=1)).exclude(
        cause=HogWakeCause.USER.value
    )
    if recent.filter(refused=False).count() < MAX_AUTOMATIC_WAKES_PER_HOUR:
        return True
    already_told = recent.filter(refused=True).exists()
    HogWake.objects.create(team_id=hog.team_id, hog=hog, cause=cause.value, hops=hops, refused=True)
    if not already_told:
        message = HogMessage.objects.create(
            team_id=hog.team_id,
            hog=hog,
            author=HogMessageAuthor.SYSTEM.value,
            content=(
                f"{hog.name} reached its limit of {MAX_AUTOMATIC_WAKES_PER_HOUR} automatic wakes in an hour. "
                "Schedules, triggers and notes are skipped until the hour clears. Your own messages still get through."
            ),
        )
        hog.last_message_at = message.created_at
        hog.save(update_fields=["last_message_at", "updated_at"])
    return False


def _signal_live_run(hog: Hog, trigger: str) -> bool:
    if hog.current_run_id is None or hog.current_task_id is None:
        return False
    run = tasks_facade.get_task_run(hog.current_run_id, team_id=hog.team_id)
    if run is None or run.is_terminal:
        return False
    try:
        delivered = tasks_facade.signal_task_run_user_message(
            run.id,
            run.task_id,
            hog.team_id,
            content=trigger,
            artifact_ids=[],
            actor_user_id=hog.created_by_id,
        )
    except Exception:
        logger.exception("hog_wake_signal_failed", extra={"hog_id": str(hog.id)})
        return False
    return bool(delivered)


def wake_hog(hog: Hog, *, trigger: str, cause: HogWakeCause, hops: int = 0) -> bool:
    """Give the hog something to act on. Returns False when no run could take it."""
    if hops > MAX_HOPS:
        raise WakeRefused(
            f"This note is hop {hops} in a chain of hog-to-hog notes and the limit is {MAX_HOPS}. "
            "Tell your owner with hog-say if it matters."
        )
    if not _within_hourly_cap(hog, cause, hops):
        return False
    HogWake.objects.create(team_id=hog.team_id, hog=hog, cause=cause.value, hops=hops)
    if not _signal_live_run(hog, trigger):
        try:
            created = tasks_facade.create_and_run_task(
                team=Team.objects.get(id=hog.team_id),
                title=f"Hog: {hog.name}",
                description=build_wake_prompt(hog, trigger=trigger),
                user_id=hog.created_by_id,
                profile=HOG,
                create_pr=False,
                ai_agent_name=hog.name,
                # The connector allowlist the sandbox reads when it mounts MCP store servers.
                extra_run_state={
                    "config_snapshot": {"connectors": {"mcp_installation_ids": list(hog.mcp_installation_ids)}}
                },
            )
        except Exception:
            logger.exception("hog_wake_failed", extra={"hog_id": str(hog.id)})
            HogMessage.objects.create(
                team_id=hog.team_id,
                hog=hog,
                author=HogMessageAuthor.SYSTEM.value,
                content=f"{hog.name} could not start working. Send your message again in a moment.",
            )
            return False
        hog.current_task_id = created.task_id
        hog.current_run_id = created.latest_run.id if created.latest_run else None
    hog.working_since = timezone.now()
    hog.wake_hops = hops
    hog.save(update_fields=["current_task_id", "current_run_id", "working_since", "wake_hops", "updated_at"])
    return True


def is_working(hog: Hog) -> bool:
    return hog.working_since is not None and timezone.now() - hog.working_since < WORKING_TIMEOUT


def settle_finished_run(hog: Hog) -> None:
    """Stop showing a hog as working once its run has ended, and say so in the chat if the run failed."""
    if hog.working_since is None or hog.current_run_id is None:
        return
    run = tasks_facade.get_task_run(hog.current_run_id, team_id=hog.team_id)
    # A run that cannot be read tells us nothing, so the working timeout decides instead.
    if run is None or not run.is_terminal:
        return
    hog.working_since = None
    hog.save(update_fields=["working_since", "updated_at"])
    if run.status == tasks_facade.TaskRunStatus.FAILED:
        message = HogMessage.objects.create(
            team_id=hog.team_id,
            hog=hog,
            author=HogMessageAuthor.SYSTEM.value,
            content=f"{hog.name} stopped before finishing. {run.error_message or 'The run failed.'}",
            task_run_id=run.id,
        )
        hog.last_message_at = message.created_at
        hog.save(update_fields=["last_message_at", "updated_at"])
