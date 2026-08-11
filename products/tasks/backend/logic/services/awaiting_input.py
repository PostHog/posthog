"""Tracks which permission request a run is blocked on, from the sandbox event stream.

The agent's permission prompts live in the run's log, so only a client with a live session
attached to the run knows the agent is waiting on a person. Everything else — a task list, a
second device, a client that has not opened the task — polls the API and sees a run that is
still ``in_progress``, which reads as "working" when it is really "waiting". Recording the
request id on the run turns that into a polled fact.
"""

from typing import Any

import structlog

from products.tasks.backend.logic.services.permission_broker import (
    POSTHOG_PERMISSION_REQUEST_METHOD,
    parse_permission_request,
)
from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

PERMISSION_RESOLVED_METHOD = "_posthog/permission_resolved"


def _notification_params(event_data: Any, method: str) -> dict[str, Any] | None:
    if not isinstance(event_data, dict):
        return None
    notification = event_data.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != method:
        return None
    params = notification.get("params")
    return params if isinstance(params, dict) else None


def is_permission_lifecycle_event(event_data: Any) -> bool:
    """Whether this event can change the run's awaiting-input state.

    Pure, so the ingest path can skip the database for the overwhelming majority of events.
    """
    if not isinstance(event_data, dict):
        return False
    if event_data.get("type") == "permission_request":
        return True
    notification = event_data.get("notification")
    if not isinstance(notification, dict):
        return False
    return notification.get("method") in (POSTHOG_PERMISSION_REQUEST_METHOD, PERMISSION_RESOLVED_METHOD)


def parse_permission_resolved_request_id(event_data: Any) -> str | None:
    """The request id an ACP ``permission_resolved`` notification settles, if it is one."""
    params = _notification_params(event_data, PERMISSION_RESOLVED_METHOD)
    if params is None:
        return None
    request_id = params.get("requestId")
    return request_id if isinstance(request_id, str) and request_id else None


def mark_run_awaiting_input(run_id: str, request_id: str) -> None:
    """Record that ``run_id`` is blocked on ``request_id``."""
    TaskRun.objects.filter(id=run_id).update(awaiting_input_request_id=request_id)


def clear_run_awaiting_input(run_id: str, request_id: str | None = None) -> None:
    """Record that ``run_id`` is no longer blocked.

    Pass ``request_id`` when a specific request was answered, so settling an earlier request
    cannot clear a newer one the agent has since raised. Omit it where the run cannot be
    waiting on anything — the end of a turn, or a run reaching a terminal status.
    """
    runs = TaskRun.objects.filter(id=run_id, awaiting_input_request_id__isnull=False)
    if request_id is not None:
        runs = runs.filter(awaiting_input_request_id=request_id)
    runs.update(awaiting_input_request_id=None)


def track_permission_state(run_id: str, event_data: Any) -> None:
    """Apply one sandbox event to the run's awaiting-input state. Never raises.

    Sits on the event ingest path, so a failure here must not cost the run its event.
    """
    try:
        resolved_request_id = parse_permission_resolved_request_id(event_data)
        if resolved_request_id is not None:
            clear_run_awaiting_input(run_id, resolved_request_id)
            return

        request = parse_permission_request(event_data)
        if request is not None:
            mark_run_awaiting_input(run_id, request["request_id"])
    except Exception:
        logger.warning("task_run_awaiting_input_track_failed", run_id=run_id, exc_info=True)
