"""Dispatch task notifications to the relevant users' mobile devices.

Schedules the underlying Expo HTTP call as a Celery task via
``transaction.on_commit`` so nothing here can block a request/response cycle
or a Temporal activity's event loop.

Guards before we enqueue:

Tasks created or actively continued on mobile use task pushes; report research and implementation
use the report notification channel instead. User preferences apply to both.

1. **Cooldown.** A per-source Redis lock collapses duplicate triggers in a
   short window.
2. **Access.** Recipients must still be able to view the task.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Literal, cast

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections, transaction
from django.db.models import Exists, OuterRef

import structlog

from posthog.models.user import User
from posthog.push_notifications import mobile_push_preference_enabled
from posthog.tasks.push_notifications import send_user_push

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.tasks.backend.metrics import PUSH_DISPATCHER_FAILURES_TOTAL, PUSH_DISPATCHER_OUTCOMES_TOTAL
from products.tasks.backend.mobile_push import (
    enqueue_mobile_pr_outcome,
    mobile_push_user_ids,
    suppressed_push_token_ids_for_task,
    task_mobile_push_eligible,
)
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.redis import get_tasks_cache
from products.tasks.backend.visibility import task_visibility_q

if TYPE_CHECKING:
    from uuid import UUID

    from products.tasks.backend.models import TaskThreadMessage

logger = structlog.get_logger(__name__)

PUSH_TITLE = "PostHog"
AWAITING_INPUT_COOLDOWN_SECONDS = 30

# Cooldown windows per push kind. Terminal pushes get a longer window because
# they should only fire once per run lifetime — anything more is a retry.
# Interactive turn-end can legitimately fire again after the user replies,
# so a short cooldown is enough to absorb rapid duplicate triggers.
PushKind = Literal[
    "completed",
    "failed",
    "cancelled",
    "awaiting",
    "turn_completed",
    "thread_message",
    "handoff",
    "pr_merged",
    "pr_closed",
]
_COOLDOWN_SECONDS: dict[PushKind, int] = {
    "completed": 600,
    "failed": 600,
    "cancelled": 600,
    "awaiting": AWAITING_INPUT_COOLDOWN_SECONDS,
    "turn_completed": 30,
    "thread_message": 600,
    "handoff": 600,
    "pr_merged": 600,
    "pr_closed": 600,
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


def notify_task_run_awaiting_input(task_run: TaskRun, *, on_enqueued: Callable[[], None] | None = None) -> bool:
    """Return whether a push was scheduled; on_enqueued confirms Celery accepted it after commit."""
    _project_awaiting_input_activity(task_run)
    return _enqueue(
        task_run, kind="awaiting", body=f'"{_task_title(task_run)}" needs your input', on_enqueued=on_enqueued
    )


def notify_task_run_turn_completed(task_run: TaskRun) -> None:
    _project_completed_activity(task_run)
    _enqueue(task_run, kind="turn_completed", body=f'"{_task_title(task_run)}" finished')


def notify_task_pull_request_outcome(*, task_id: str, run_id: str, team_id: int, pr_url: str, merged: bool) -> None:
    """Push a verified PR outcome independently of whether Slack announced the PR."""
    kind: PushKind = "pr_merged" if merged else "pr_closed"
    try:
        task_run = TaskRun.objects.filter(id=run_id, task_id=task_id, team_id=team_id).select_related("task").first()
        if task_run is None:
            return
        outcome = "merged" if merged else "closed"
        _enqueue_inner(
            task_run, kind=kind, body=f'"{_task_title(task_run)}" pull request was {outcome}', pull_request_url=pr_url
        )
    except Exception as exc:
        PUSH_DISPATCHER_FAILURES_TOTAL.labels(kind=kind, reason=_failure_reason(exc)).inc()
        logger.warning("push_dispatcher.pr_outcome_failed", task_id=task_id, team_id=team_id, exc_info=True)


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
    message.task.refresh_from_db(fields=["state"])
    recipient_ids = set(mentioned_user_ids) | mobile_push_user_ids(message.task)
    if message.task.created_by_id is not None:
        recipient_ids.add(message.task.created_by_id)
    if message.author_id is not None:
        recipient_ids.discard(message.author_id)

    mentioned = set(mentioned_user_ids)
    author = message.author
    author_name = (author.first_name.strip() or author.email) if author else "PostHog"
    task_title = (message.task.title or "").strip() or "Untitled task"
    data: dict[str, str | int] = {
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
    for users with no push device, and it has no cooldown to observe. Best-effort
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


def _enqueue(task_run: TaskRun, *, kind: PushKind, body: str, on_enqueued: Callable[[], None] | None = None) -> bool:
    """Best-effort: this function MUST NOT raise.

    Wrap the whole body in a bare ``except Exception`` so a DB outage,
    Redis hiccup, or any other surprise can't bubble
    out of ``mark_completed`` / ``mark_failed`` / the API cancel handler
    and fail the surrounding task-lifecycle activity.
    """
    try:
        return _enqueue_inner(task_run, kind=kind, body=body, on_enqueued=on_enqueued)
    except Exception as exc:
        PUSH_DISPATCHER_FAILURES_TOTAL.labels(kind=kind, reason=_failure_reason(exc)).inc()
        logger.warning(
            "push_dispatcher.enqueue_failed",
            run_id=str(task_run.id),
            task_id=str(task_run.task_id),
            kind=kind,
            exc_info=True,
        )
        return False


def _failure_reason(exc: BaseException) -> str:
    return "db_connection" if isinstance(exc, OperationalError | InterfaceError) else "other"


def _enqueue_inner(
    task_run: TaskRun,
    *,
    kind: PushKind,
    body: str,
    pull_request_url: str | None = None,
    on_enqueued: Callable[[], None] | None = None,
) -> bool:
    if not settings.TEST:
        close_old_connections()

    from products.signals.backend.facade.api import (  # noqa: PLC0415 — avoid a product import cycle
        notify_report_task_push,
    )

    if notify_report_task_push(
        team_id=task_run.team_id,
        task_id=str(task_run.task_id),
        run_id=str(task_run.id),
        kind=kind,
        pull_request_url=pull_request_url,
        on_enqueued=on_enqueued,
    ):
        return True

    task = Task.objects.filter(id=task_run.task_id, team_id=task_run.team_id).first()
    if task is None:
        return False
    recipient_ids = mobile_push_user_ids(task)
    if task.created_by_id is not None:
        recipient_ids.add(task.created_by_id)
    if not recipient_ids:
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="no_recipient").inc()
        return False
    subject = (
        f"pr:{task.id}:{hashlib.sha256(pull_request_url.encode()).hexdigest()}"
        if pull_request_url
        else str(task_run.id)
    )
    accepted = False
    for user in User.objects.filter(id__in=recipient_ids):
        data: dict[str, str | int] = {"taskId": str(task.id), "taskRunId": str(task_run.id)}
        if pull_request_url is not None:
            data["pullRequestUrl"] = pull_request_url
        enqueued = _enqueue_user(
            user,
            task=task,
            kind=kind,
            cooldown_subject=f"{subject}:{user.id}",
            body=body,
            data=data,
            pull_request_url=pull_request_url,
            on_enqueued=on_enqueued,
        )
        accepted = accepted or enqueued
    return accepted


def _enqueue_user(
    user: User,
    *,
    task: Task,
    kind: PushKind,
    cooldown_subject: str,
    body: str,
    data: dict[str, str | int],
    pull_request_url: str | None = None,
    on_enqueued: Callable[[], None] | None = None,
) -> bool:
    task.refresh_from_db(fields=["state"])
    if task.is_scout_experiment:
        return False
    if not task_mobile_push_eligible(task, user.id):
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="source_disabled").inc()
        return False
    if not mobile_push_preference_enabled(user, "tasks"):
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="preferences_disabled").inc()
        return False
    if (
        not user.teams.filter(id=task.team_id).exists()
        or not UserAccessControl(user=user, team=task.team).check_access_level_for_resource("task", "viewer")
        or not Task.objects.filter(id=task.id, team_id=task.team_id, deleted=False)
        .filter(task_visibility_q(user.id))
        .exists()
    ):
        PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="access_denied").inc()
        return False
    cooldown_key = f"push_notification:{cooldown_subject}:{kind}"
    suppressed = suppressed_push_token_ids_for_task(user_id=user.id, task_id=task.id, team_id=task.team_id)
    data["type"] = "task"
    data["notificationKind"] = kind
    data["projectId"] = task.team_id

    # on_commit so we never schedule a push for a write that ends up rolling
    # back. Outside an atomic block this fires immediately, which is fine.
    accepted = True

    def dispatch() -> None:
        nonlocal accepted
        try:
            if not get_tasks_cache().add(cooldown_key, True, timeout=_COOLDOWN_SECONDS[kind]):
                PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome="cooldown_deduped").inc()
                accepted = False
                return
            try:

                def enqueue() -> None:
                    send_user_push.delay(user.id, PUSH_TITLE, body, data, suppressed)

                if pull_request_url is not None:
                    enqueued = enqueue_mobile_pr_outcome(
                        task_id=task.id,
                        team_id=task.team_id,
                        user_id=user.id,
                        pr_url=pull_request_url,
                        kind=kind,
                        enqueue=enqueue,
                    )
                else:
                    enqueue()
                    enqueued = True
                if enqueued:
                    outcome = "presence_suppressed" if suppressed else "enqueued"
                    PUSH_DISPATCHER_OUTCOMES_TOTAL.labels(kind=kind, outcome=outcome).inc()
                    if on_enqueued is not None:
                        on_enqueued()
                else:
                    accepted = False
            except Exception:
                get_tasks_cache().delete(cooldown_key)
                raise
        except Exception as exc:
            accepted = False
            PUSH_DISPATCHER_FAILURES_TOTAL.labels(kind=kind, reason=_failure_reason(exc)).inc()
            logger.warning(
                "push_dispatcher.enqueue_failed", task_id=str(task.id), user_id=user.id, kind=kind, exc_info=True
            )

    transaction.on_commit(dispatch)
    return accepted
