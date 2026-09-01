"""Dispatch task notifications to the relevant users' mobile devices.

Schedules the underlying Expo HTTP call as a Celery task via
``transaction.on_commit`` so nothing here can block a request/response cycle
or a Temporal activity's event loop.

Three guards before we enqueue:

1. **Feature flag.** ``posthog-code-mobile-push`` must be enabled for the
   user. Off by default — flip on once the mobile build is ready and
   tokens start arriving.
2. **Cooldown.** A per-source Redis lock collapses duplicate triggers in a
   short window.
3. **Access.** Recipients must still be able to view the task.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Literal, cast

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.models.user import User
from posthog.models.user_push_token import UserPushToken
from posthog.tasks.push_notifications import send_user_push

from products.tasks.backend.metrics import PUSH_DISPATCHER_FAILURES_TOTAL, PUSH_DISPATCHER_OUTCOMES_TOTAL
from products.tasks.backend.models import Task, TaskPresence
from products.tasks.backend.redis import get_tasks_cache
from products.tasks.backend.visibility import task_visibility_q

if TYPE_CHECKING:
    from uuid import UUID

    from products.tasks.backend.models import TaskRun, TaskThreadMessage

logger = structlog.get_logger(__name__)

PUSH_TITLE = "PostHog Desktop"
FEATURE_FLAG_KEY = "posthog-code-mobile-push"

# Cooldown windows per push kind. Terminal pushes get a longer window because
# they should only fire once per run lifetime — anything more is a retry.
# Interactive turn-end can legitimately fire again after the user replies,
# so a short cooldown is enough to absorb rapid duplicate triggers.
PushKind = Literal["completed", "failed", "cancelled", "awaiting", "turn_completed", "thread_message", "handoff"]
_COOLDOWN_SECONDS: dict[PushKind, int] = {
    "completed": 600,
    "failed": 600,
    "cancelled": 600,
    "awaiting": 30,
    "turn_completed": 30,
    "thread_message": 600,
    "handoff": 600,
}


def notify_task_run_completed(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` finishes successfully."""
    _project_completed_activity(task_run)
    _enqueue(task_run, kind="completed", body=f'"{_task_title(task_run)}" finished')


def notify_task_run_failed(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` ends with a failure."""
    _enqueue(task_run, kind="failed", body=f'"{_task_title(task_run)}" failed')


def notify_task_run_cancelled(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` is cancelled."""
    _enqueue(task_run, kind="cancelled", body=f'"{_task_title(task_run)}" was cancelled')


def notify_task_run_awaiting_input(task_run: TaskRun) -> None:
    """Fire a push notification when an interactive run is waiting for user input."""
    _project_awaiting_input_activity(task_run)
    _enqueue(task_run, kind="awaiting", body=f'"{_task_title(task_run)}" needs your input')


def notify_task_run_turn_completed(task_run: TaskRun) -> None:
    _project_completed_activity(task_run)
    _enqueue(task_run, kind="turn_completed", body=f'"{_task_title(task_run)}" finished')


def notify_task_handoff(task: Task, *, recipient: User, actor: User | None, message_id: UUID) -> None:
    """Fire a push notification when a task is handed off to ``recipient``.

    The announcement ID separates new handoffs from retries for cooldown purposes.
    """
    try:
        actor_name = ((actor.first_name.strip() or actor.email) if actor else None) or "A colleague"
        task_title = (task.title or "").strip() or "Untitled task"
        _enqueue_user(
            recipient,
            task=task,
            kind="handoff",
            cooldown_subject=f"task_handoff:{message_id}:{recipient.id}",
            body=f'{actor_name} handed you "{task_title}"',
            data={"taskId": str(task.id)},
        )
    except Exception as exc:
        PUSH_DISPATCHER_FAILURES_TOTAL.labels(kind="handoff", reason=_failure_reason(exc)).inc()
        logger.warning(
            "push_dispatcher.enqueue_failed",
            task_id=str(task.id),
            user_id=recipient.id,
            kind="handoff",
            exc_info=True,
        )


def notify_task_thread_message(message: TaskThreadMessage, mentioned_user_ids: Collection[int]) -> None:
    try:
        _notify_task_thread_message(message, mentioned_user_ids)
    except Exception as exc:
        PUSH_DISPATCHER_FAILURES_TOTAL.labels(kind="thread_message", reason=_failure_reason(exc)).inc()
        logger.warning(
            "push_dispatcher.enqueue_failed",
            task_id=str(message.task_id),
            message_id=str(message.id),
            kind="thread_message",
            exc_info=True,
        )


def _notify_task_thread_message(message: TaskThreadMessage, mentioned_user_ids: Collection[int]) -> None:
    recipient_ids = set(mentioned_user_ids)
    if message.task.created_by_id is not None:
        recipient_ids.add(message.task.created_by_id)
    if message.author_id is not None:
        recipient_ids.discard(message.author_id)

    mentioned = set(mentioned_user_ids)
    author = message.author
    author_name = (author.first_name.strip() or author.email) if author else "PostHog"
    task_title = (message.task.title or "").strip() or "Untitled task"
    data = {
        "taskId": str(message.task_id),
        "messageId": str(message.id),
    }
    visible_task = Task.objects.filter(team_id=message.team_id, deleted=False).filter(
        task_visibility_q(cast(int, OuterRef("id"))), id=message.task_id
    )
    recipients = User.objects.filter(id__in=recipient_ids).filter(Exists(visible_task))
    for user in recipients:
        if not user.teams.filter(id=message.team_id).exists():
            continue
        action = "mentioned you" if user.id in mentioned else "replied"
        try:
            _enqueue_user(
                user,
                task=message.task,
                kind="thread_message",
                cooldown_subject=f"{message.id}:{user.id}",
                body=f'{author_name} {action} in "{task_title}"',
                data=data,
            )
        except Exception as exc:
            PUSH_DISPATCHER_FAILURES_TOTAL.labels(kind="thread_message", reason=_failure_reason(exc)).inc()
            logger.warning(
                "push_dispatcher.enqueue_failed",
                task_id=str(message.task_id),
                message_id=str(message.id),
                user_id=user.id,
                kind="thread_message",
                exc_info=True,
            )


def _project_awaiting_input_activity(task_run: TaskRun) -> None:
    """Surface the wait in the in-app Activity feed.

    Runs ahead of, and independently of, the push guards above: the feed should update even
    for users without the mobile push flag, and it has no cooldown to observe. Best-effort
    for the same reason ``_enqueue`` is — this sits on the agent's turn-end path and must
    never fail it.
    """
    try:
        from products.tasks.backend.facade.api import (  # noqa: PLC0415 - keeps the facade off the push import path
            project_awaiting_input_activity,
        )

        project_awaiting_input_activity(task_run)
    except Exception:
        logger.warning("push_dispatcher.activity_projection_failed", run_id=str(task_run.id), exc_info=True)


def _project_completed_activity(task_run: TaskRun) -> None:
    try:
        from products.tasks.backend.facade.api import (  # noqa: PLC0415 - keeps the facade off the push import path
            project_completed_activity,
        )

        project_completed_activity(task_run)
    except Exception:
        logger.warning("push_dispatcher.activity_projection_failed", run_id=str(task_run.id), exc_info=True)


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
    except Exception as exc:
        PUSH_DISPATCHER_FAILURES_TOTAL.labels(kind=kind, reason=_failure_reason(exc)).inc()
        logger.warning(
            "push_dispatcher.enqueue_failed",
            run_id=str(task_run.id),
            task_id=str(task_run.task_id),
            kind=kind,
            exc_info=True,
        )


def _failure_reason(exc: BaseException) -> str:
    return "db_connection" if isinstance(exc, OperationalError | InterfaceError) else "other"


def _enqueue_inner(task_run: TaskRun, *, kind: PushKind, body: str) -> None:
    if not settings.TEST:
        close_old_connections()

    user = task_run.task.created_by
    if user is None:
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="no_recipient").inc()
        return

    if not user.teams.filter(id=task_run.team_id).exists():
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="access_denied").inc()
        logger.debug(
            "push_dispatcher.recipient_lost_access",
            user_id=user.id,
            task_id=str(task_run.task_id),
            team_id=task_run.team_id,
        )
        return

    _enqueue_user(
        user,
        task=task_run.task,
        kind=kind,
        cooldown_subject=str(task_run.id),
        body=body,
        data={"taskId": str(task_run.task_id), "taskRunId": str(task_run.id)},
    )


def _enqueue_user(
    user: User,
    *,
    task: Task,
    kind: PushKind,
    cooldown_subject: str,
    body: str,
    data: dict[str, str],
) -> None:
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
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="flag_check_failed").inc()
        return
    if not flag_enabled:
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="flag_disabled").inc()
        return

    cooldown_key = f"push_notification:{cooldown_subject}:{kind}"
    if not get_tasks_cache().add(cooldown_key, True, timeout=_COOLDOWN_SECONDS[kind]):
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="cooldown_deduped").inc()
        logger.debug("push_dispatcher.cooldown_hit", subject=cooldown_subject, kind=kind)
        return

    suppressed = _suppressed_push_token_ids_for_task(user_id=user.id, task_id=task.id)
    data["notificationKind"] = kind

    # on_commit so we never schedule a push for a write that ends up rolling
    # back. Outside an atomic block this fires immediately, which is fine.
    def dispatch() -> None:
        outcome = "presence_suppressed" if suppressed else "enqueued"
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome=outcome).inc()
        send_user_push.delay(user.id, PUSH_TITLE, body, data, suppressed)

    transaction.on_commit(dispatch)


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
