"""Auto-responder for sandbox agent permission requests from Slack-origin runs.

Slack-origin runs launch their sandbox session in ``bypassPermissions`` mode, so
they should never raise a ``permission_request`` event. Runs whose sandbox still
asks — sessions started before the bypass mode rolled out, or a runtime that asks
despite it — would stall until the run's inactivity timeout now that Slack has no
approval surface, so the relay answers every such request here with the default
allow option, authenticated as the run's credential user. Requests from other
origin surfaces (web UI, PostHog AI) are left untouched; those surfaces read the
event stream and answer directly.
"""

from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import structlog

from products.tasks.backend.logic.services.agent_command import send_agent_command
from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.logic.services.run_actor import get_actor_distinct_id, get_task_run_credential_user
from products.tasks.backend.models import Task

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

POSTHOG_PERMISSION_REQUEST_METHOD = "_posthog/permission_request"
# Must comfortably outlive the run so a replayed relay event can't double-answer.
AUTO_RESPONSE_DEDUPE_SECONDS = 24 * 60 * 60


def _auto_response_dedupe_key(run_id: str, request_id: str) -> str:
    return f"tasks:permission_auto_response:v1:{run_id}:{request_id}"


def _permission_request_payload(event_data: dict[str, Any]) -> dict[str, Any] | None:
    if event_data.get("type") == "permission_request":
        return event_data

    notification = event_data.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != POSTHOG_PERMISSION_REQUEST_METHOD:
        return None

    params = notification.get("params")
    return params if isinstance(params, dict) else None


def _normalize_permission_options(options: Any) -> list[dict[str, str]]:
    if not isinstance(options, list):
        return []

    normalized: list[dict[str, str]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        option_id = option.get("optionId")
        kind = option.get("kind")
        name = option.get("name")
        if not isinstance(option_id, str) or not option_id:
            continue
        normalized.append(
            {
                "optionId": option_id,
                "kind": kind if isinstance(kind, str) else "",
                "name": name if isinstance(name, str) else "",
            }
        )
    return normalized


def parse_permission_request(event_data: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a sandbox permission_request event (bare or ACP-notification shaped).

    Returns ``{"request_id": str, "tool_call": dict, "options": [{optionId, kind, name}]}``
    or ``None`` when the event isn't a well-formed permission request.
    """
    payload = _permission_request_payload(event_data)
    if payload is None:
        return None

    request_id = payload.get("requestId")
    tool_call = payload.get("toolCall")
    options = _normalize_permission_options(payload.get("options"))
    if not isinstance(request_id, str) or not request_id or not isinstance(tool_call, dict) or not options:
        return None

    return {
        "request_id": request_id,
        "tool_call": tool_call,
        "options": options,
    }


def _default_allow_option_id(options: list[dict[str, str]]) -> str | None:
    allow_options = [option for option in options if not option["kind"].startswith("reject")]
    default_option = next((option for option in allow_options if option["kind"] == "allow_once"), None)
    if default_option is not None:
        return default_option["optionId"]
    return allow_options[0]["optionId"] if allow_options else None


def try_auto_respond_permission_request(task_run: "TaskRun", permission_request: dict[str, Any]) -> bool:
    """Allow a Slack-origin run's permission request so the agent never blocks on one.

    Returns ``True`` when the request was answered (now or previously); ``False``
    when the run belongs to another origin surface or the response couldn't be sent.
    """
    task = task_run.task
    if task.origin_product != Task.OriginProduct.SLACK:
        return False

    request_id = permission_request["request_id"]
    run_id = str(task_run.id)
    dedupe_key = _auto_response_dedupe_key(run_id, request_id)
    if cache.get(dedupe_key):
        return True

    option_id = _default_allow_option_id(permission_request["options"])
    if option_id is None:
        logger.info("permission_broker_no_allow_option", run_id=run_id, request_id=request_id)
        return False

    state = task_run.state if isinstance(task_run.state, dict) else {}
    actor = get_task_run_credential_user(task, state)
    if actor is None:
        logger.info("permission_broker_no_credential_actor", run_id=run_id, request_id=request_id)
        return False

    auth_token = create_sandbox_connection_token(
        task_run,
        user_id=actor.id,
        distinct_id=get_actor_distinct_id(actor),
    )
    result = send_agent_command(
        task_run,
        method="permission_response",
        params={"requestId": request_id, "optionId": option_id},
        auth_token=auth_token,
    )
    if not result.success:
        logger.warning(
            "permission_broker_auto_allow_failed",
            run_id=run_id,
            request_id=request_id,
            option_id=option_id,
            actor_user_id=actor.id,
            status_code=result.status_code,
            error=result.error,
        )
        return False

    cache.set(dedupe_key, True, timeout=AUTO_RESPONSE_DEDUPE_SECONDS)
    logger.info(
        "permission_broker_auto_allowed",
        run_id=run_id,
        request_id=request_id,
        option_id=option_id,
        actor_user_id=actor.id,
    )
    return True
