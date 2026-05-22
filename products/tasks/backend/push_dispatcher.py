"""Dispatch push notifications to the task creator's mobile devices.

Schedules the underlying Expo HTTP call as a Celery task via
``transaction.on_commit`` so nothing here can block a request/response cycle
or a Temporal activity's event loop.

Three guards before we enqueue:

1. **Feature flag.** ``posthog-code-mobile-push`` must be enabled for the
   user. Off by default — flip on once the mobile build is ready and
   tokens start arriving.
2. **Cooldown.** A per-``(task_run, kind)`` Redis lock collapses duplicate
   triggers in a short window. A workflow that retries ``mark_completed``
   or an agent that fires several rapid end-of-turn events results in one
   push, not five.
3. **Anonymous task.** Runs without a ``created_by`` user get skipped
   silently — there's no one to notify.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.models.user_push_token import UserPushToken
from posthog.tasks.push_notifications import send_user_push

from products.tasks.backend.models import TaskPresence

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

PUSH_TITLE = "PostHog Code"
FEATURE_FLAG_KEY = "posthog-code-mobile-push"

# Cooldown windows per push kind. Terminal pushes get a longer window because
# they should only fire once per run lifetime — anything more is a retry.
# Interactive turn-end can legitimately fire again after the user replies,
# so a short cooldown is enough to absorb rapid duplicate triggers.
PushKind = Literal["completed", "failed", "cancelled", "awaiting"]
_COOLDOWN_SECONDS: dict[PushKind, int] = {
    "completed": 600,
    "failed": 600,
    "cancelled": 600,
    "awaiting": 30,
}


def notify_task_run_completed(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` finishes successfully."""
    _enqueue(task_run, kind="completed", body=f'"{_task_title(task_run)}" finished')


def notify_task_run_failed(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` ends with a failure."""
    _enqueue(task_run, kind="failed", body=f'"{_task_title(task_run)}" failed')


def notify_task_run_cancelled(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` is cancelled."""
    _enqueue(task_run, kind="cancelled", body=f'"{_task_title(task_run)}" was cancelled')


def notify_task_run_awaiting_input(task_run: TaskRun) -> None:
    """Fire a push notification when an interactive run is waiting for user input."""
    _enqueue(task_run, kind="awaiting", body=f'"{_task_title(task_run)}" needs your input')


def _task_title(task_run: TaskRun) -> str:
    title = (task_run.task.title or "").strip()
    return title or "Untitled task"


def _enqueue(task_run: TaskRun, *, kind: PushKind, body: str) -> None:
    """Best-effort: this function MUST NOT raise.

    Wrap the whole body in a bare ``except Exception`` so a DB outage,
    Redis hiccup, flag-service failure, or any other surprise can't bubble
    out of ``mark_completed`` / ``mark_failed`` / the API cancel handler
    and fail the surrounding task-lifecycle activity.
    """
    try:
        _enqueue_inner(task_run, kind=kind, body=body)
    except Exception:
        logger.warning(
            "push_dispatcher.enqueue_failed",
            run_id=str(task_run.id),
            task_id=str(task_run.task_id),
            kind=kind,
            exc_info=True,
        )


def _enqueue_inner(task_run: TaskRun, *, kind: PushKind, body: str) -> None:
    user = task_run.task.created_by
    if user is None:
        return

    # If the user has lost access to the task's team (e.g. removed from the
    # organization), don't push them task titles for runs they shouldn't see
    # anymore. The push body and data payload both carry the task identity.
    # `user.teams` already accounts for both org membership and project-level
    # RBAC, so it's the most accurate "can this user still see this run" gate.
    if not user.teams.filter(id=task_run.team_id).exists():
        logger.debug(
            "push_dispatcher.recipient_lost_access",
            user_id=user.id,
            run_id=str(task_run.id),
            team_id=task_run.team_id,
        )
        return

    distinct_id = user.distinct_id or f"user_{user.id}"
    try:
        flag_enabled = posthoganalytics.feature_enabled(
            FEATURE_FLAG_KEY,
            distinct_id,
            send_feature_flag_events=False,
        )
    except Exception:
        # Failing closed on flag-evaluation errors keeps an outage from
        # silently flipping pushes on for the whole user base.
        logger.warning("push_dispatcher.flag_check_failed", user_id=user.id, exc_info=True)
        return
    if not flag_enabled:
        return

    cooldown_key = f"push_notification:{task_run.id}:{kind}"
    if not cache.add(cooldown_key, True, timeout=_COOLDOWN_SECONDS[kind]):
        logger.debug("push_dispatcher.cooldown_hit", run_id=str(task_run.id), kind=kind)
        return

    data = {"taskId": str(task_run.task_id), "taskRunId": str(task_run.id)}
    suppressed = _suppressed_push_token_ids_for_task(user_id=user.id, task_id=task_run.task_id)

    # on_commit so we never schedule a push for a write that ends up rolling
    # back. Outside an atomic block this fires immediately, which is fine.
    transaction.on_commit(lambda: send_user_push.delay(user.id, PUSH_TITLE, body, data, suppressed))


def _suppressed_push_token_ids_for_task(*, user_id: int, task_id) -> list[str]:
    """Return all of the user's UserPushToken UUIDs (as strings) when at least one device
    has beaconed presence for this task — otherwise an empty list.

    The contract documented on the beacon endpoint is "if any device is
    provably watching, suppress the others". The watching device doesn't need
    a push either — it's already rendering the task UI in real time — so when
    any presence row is active we suppress the entire fanout for the user.
    Computed at enqueue time; the Celery dispatch is essentially instant so
    the race window against the 30-second beacon cadence is irrelevant.

    ``unscoped`` is the right escape hatch here: the dispatcher fires from a
    mix of Temporal activities and model methods that don't have the DRF
    team-context ContextVar set. Both queries are scoped through
    ``user_id`` and ``task_id`` and the presence rows are tenant-safe by
    virtue of their FK to a team-scoped Task.
    """
    has_active_presence = (
        TaskPresence.objects.unscoped().filter(task_id=task_id, user_id=user_id, expires_at__gt=timezone.now()).exists()
    )
    if not has_active_presence:
        return []
    return [str(pid) for pid in UserPushToken.objects.filter(user_id=user_id).values_list("id", flat=True)]
