"""Dispatch push notifications to the task creator's mobile devices.

Wrapper around ``posthog.push_notifications`` that handles the
PostHog-Code-specific event shape: title, body, and data payload pointing at
the relevant task / task run.

All entry points swallow exceptions and log instead of raising — pushes are
best-effort and must never interfere with the task lifecycle.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from posthog.push_notifications import send_push_to_user

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

PUSH_TITLE = "PostHog Code"


def notify_task_run_completed(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` finishes successfully."""
    _notify(task_run, body=f'"{_task_title(task_run)}" finished')


def notify_task_run_failed(task_run: TaskRun) -> None:
    """Fire a push notification when ``task_run`` ends with a failure."""
    _notify(task_run, body=f'"{_task_title(task_run)}" failed')


def notify_task_run_awaiting_input(task_run: TaskRun) -> None:
    """Fire a push notification when an interactive run is waiting for user input."""
    _notify(task_run, body=f'"{_task_title(task_run)}" needs your input')


async def notify_task_run_awaiting_input_async(task_run: TaskRun) -> None:
    """Async wrapper for use inside Temporal activities.

    Offloads the synchronous HTTP call to a thread so it doesn't block the
    activity's event loop while the Expo push API is being called.
    """
    await asyncio.to_thread(notify_task_run_awaiting_input, task_run)


def _task_title(task_run: TaskRun) -> str:
    title = (task_run.task.title or "").strip()
    return title or "Untitled task"


def _notify(task_run: TaskRun, *, body: str) -> None:
    user = task_run.task.created_by
    if user is None:
        return

    try:
        send_push_to_user(
            user,
            title=PUSH_TITLE,
            body=body,
            data={"taskId": str(task_run.task_id), "taskRunId": str(task_run.id)},
        )
    except Exception as exc:
        logger.warning(
            "push_dispatcher.send_failed",
            run_id=str(task_run.id),
            task_id=str(task_run.task_id),
            error=str(exc),
        )
