"""Owner deactivation handling for Loops.

See products/tasks/docs/LOOPS.md "Lifecycle and reconciliation": deactivating a user is often
the security response, so every loop they own must pause immediately (not lazily at next fire)
and their in-flight runs must be cancelled. A live sandbox must never keep running with that
owner's freshly minted credentials after the account has been deactivated.

Wired from the ``pre_save`` signal on ``User`` in ``posthog/models/user.py``.
"""

import logging

from django.db.models import Q
from django.utils import timezone as django_timezone

from products.tasks.backend.loop_service import pause_loop_schedules
from products.tasks.backend.models import Loop, TaskRun

logger = logging.getLogger(__name__)

_NON_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)


def pause_loops_for_deactivated_user(user_id: int) -> None:
    """Pause every enabled loop owned by a deactivated user and cancel their in-flight runs.

    Best-effort per loop: one loop's Temporal failure never stops the rest from being paused.
    Safe to call for a user with no loops.
    """
    loops = list(Loop.objects.unscoped().filter(created_by_id=user_id, enabled=True, deleted=False))
    for loop in loops:
        try:
            _pause_loop_and_cancel_runs(loop)
        except Exception:
            logger.exception("loop_lifecycle.owner_deactivation_pause_failed", extra={"loop_id": str(loop.id)})


def _pause_loop_and_cancel_runs(loop: Loop) -> None:
    loop.enabled = False
    loop.save(update_fields=["enabled", "updated_at"])
    pause_loop_schedules(loop)

    now = django_timezone.now()
    # Matches both the FK (`Task.loop`) and the pre-FK run-state snapshot (`TaskRun.state["loop_id"]`),
    # same transitional lookup as `facade/loops.py::list_loop_runs`.
    TaskRun.objects.filter(
        Q(task__loop_id=loop.id) | Q(state__loop_id=str(loop.id)),
        team_id=loop.team_id,
        status__in=_NON_TERMINAL_TASK_RUN_STATUSES,
    ).update(status=TaskRun.Status.CANCELLED, completed_at=now, updated_at=now)


__all__ = ["pause_loops_for_deactivated_user"]
