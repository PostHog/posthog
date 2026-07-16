"""Slack approval cards for sandbox agent permission requests.

The decision of whether a request needs a human at all is made in the task run
(``products/tasks/backend/logic/services/permission_broker.py``); this module only
renders the Slack prompt for requests the broker escalated, and the interactivity
handlers in ``products/slack_app/backend/api.py`` translate the resulting clicks
into the run's durable permission-response workflow signal.
"""

import time
import uuid
import hashlib
from typing import Any

from django.core.cache import cache

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegration

logger = structlog.get_logger(__name__)

SLACK_PERMISSION_CONTEXT_KIND = "task_permission_request"
# Must comfortably outlive the run's inactivity window (1h for user-origin runs)
# so a late click gets a "run already finished" reply instead of dead buttons.
SLACK_PERMISSION_CONTEXT_TTL_SECONDS = 24 * 60 * 60
SLACK_PERMISSION_PROMPT_DEDUPE_SECONDS = SLACK_PERMISSION_CONTEXT_TTL_SECONDS
SLACK_PERMISSION_PROMPT_INFLIGHT_SECONDS = 30
SLACK_CARD_BODY_MAX_LENGTH = 200

SLACK_PERMISSION_BLOCK_ID_PREFIX = "posthog_code_permission"
SLACK_PERMISSION_ACTION_APPROVE = "posthog_code_permission_approve"
SLACK_PERMISSION_ACTION_DENY = "posthog_code_permission_deny"
SLACK_PERMISSION_ACTION_SELECT = "posthog_code_permission_select"


def _interactivity_context_cache_key(context_token: str) -> str:
    # The interactivity dispatcher already resolves ownership through this shared context namespace.
    token_hash = hashlib.sha256(context_token.encode("utf-8")).hexdigest()
    return f"posthog_code_repo_picker_ctx:{token_hash}"


def _permission_prompt_dedupe_key(run_id: str, request_id: str) -> str:
    return f"posthog_code:permission_prompt:v1:{run_id}:{request_id}"


def _permission_prompt_inflight_key(run_id: str, request_id: str) -> str:
    return f"posthog_code:permission_prompt_inflight:v1:{run_id}:{request_id}"


def _slack_mapping_for_task_run(task_run: Any) -> Any:
    from products.slack_app.backend.models import SlackThreadTaskMapping

    return (
        SlackThreadTaskMapping.objects.select_related("integration")
        .filter(task_run=task_run)
        .order_by("-updated_at")
        .first()
    )


def _truncate_slack_text(value: str, max_length: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_length:
        return cleaned
    if max_length <= 1:
        return cleaned[:max_length]
    return cleaned[: max_length - 1].rstrip() + "…"


def _extract_tool_summary(permission_request: dict[str, Any]) -> tuple[str, str | None]:
    tool_call = permission_request["tool_call"]
    raw_input = tool_call.get("rawInput")
    raw_input = raw_input if isinstance(raw_input, dict) else {}
    title = tool_call.get("title") if isinstance(tool_call.get("title"), str) else None
    tool_name = permission_request.get("tool_name")
    tool_name = tool_name if isinstance(tool_name, str) and tool_name else None
    description = raw_input.get("description") if isinstance(raw_input.get("description"), str) else None
    command = raw_input.get("command") if isinstance(raw_input.get("command"), str) else None

    label = description or title or tool_name or "Run tool"
    detail = command
    return _truncate_slack_text(label, 150), _truncate_slack_text(detail, 1200) if detail else None


def _build_card_body(tool_label: str, tool_detail: str | None) -> str:
    body = tool_label
    if tool_detail:
        body = f"{body}. Command: {tool_detail}"
    return _truncate_slack_text(body, SLACK_CARD_BODY_MAX_LENGTH)


def _permission_option_label(option: dict[str, Any]) -> str:
    kind = option.get("kind")
    if kind == "allow_once":
        return "Allow"
    if kind == "allow_always":
        return "Always allow this command"
    if kind == "reject_once":
        return "Deny"
    name = option.get("name")
    return _truncate_slack_text(name, 75) if isinstance(name, str) and name.strip() else "Use this permission"


def _labeled_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{**option, "label": _permission_option_label(option)} for option in options]


def _allow_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed = [option for option in options if not option["kind"].startswith("reject")]
    return allowed or options


def _reject_option_id(options: list[dict[str, str]]) -> str | None:
    for option in options:
        if option["kind"].startswith("reject"):
            return option["optionId"]
    return None


def _build_permission_mode_option(value: str, label: str) -> dict[str, Any]:
    return {"text": {"type": "plain_text", "text": label}, "value": value}


def _current_permission_mode(task_run: Any, fallback: str) -> str:
    state = getattr(task_run, "state", None)
    if not isinstance(state, dict):
        return fallback
    mode = state.get("slack_permission_mode")
    return mode if isinstance(mode, str) else fallback


def _deny_unpostable_permission_request(task_run: Any, *, request_id: str, option_id: str | None) -> None:
    if not option_id:
        return
    try:
        from products.tasks.backend.facade import api as tasks_facade

        result = tasks_facade.respond_to_permission_request(
            task_run.id,
            task_run.task_id,
            task_run.team_id,
            request_id=request_id,
            option_id=option_id,
        )
        logger.info(
            "slack_permission_prompt_denied_after_post_failure",
            run_id=str(task_run.id),
            request_id=request_id,
            outcome=result.outcome,
        )
    except Exception:
        logger.exception(
            "slack_permission_prompt_deny_fallback_failed",
            run_id=str(task_run.id),
            request_id=request_id,
        )


def post_slack_permission_request_for_task_run(
    task_run: Any,
    permission_request: dict[str, Any],
    *,
    mapping: Any = None,
) -> None:
    """Post a Slack approval prompt for a broker-escalated sandbox permission request.

    ``permission_request`` is the normalized shape produced by
    ``products.tasks.backend.logic.services.permission_broker.parse_permission_request``.
    """
    from products.slack_app.backend.models import SlackPermissionMode

    request_id = permission_request["request_id"]
    run_id = str(task_run.id)
    dedupe_key = _permission_prompt_dedupe_key(run_id, request_id)
    if cache.get(dedupe_key):
        return

    inflight_key = _permission_prompt_inflight_key(run_id, request_id)
    if not cache.add(inflight_key, True, timeout=SLACK_PERMISSION_PROMPT_INFLIGHT_SECONDS):
        return

    try:
        mapping = mapping or _slack_mapping_for_task_run(task_run)
        if mapping is None:
            logger.info("slack_permission_prompt_no_mapping", run_id=run_id, request_id=request_id)
            return

        # Approvals authorize actions executed with the task creator's sandbox token,
        # so only the creator (the original mentioner) may answer them — never
        # whichever teammate happened to post the latest follow-up in the thread.
        target_slack_user_id = mapping.mentioning_slack_user_id
        if not target_slack_user_id:
            logger.info("slack_permission_prompt_no_target_user", run_id=run_id, request_id=request_id)
            return

        options = _labeled_options(permission_request["options"])
        allow_options = _allow_options(options)
        default_option = next((option for option in allow_options if option["kind"] == "allow_once"), allow_options[0])
        reject_option_id = _reject_option_id(options)
        if reject_option_id is None:
            logger.info("slack_permission_prompt_no_reject_option", run_id=run_id, request_id=request_id)
            return

        context_token = uuid.uuid4().hex
        tool_label, tool_detail = _extract_tool_summary(permission_request)
        cache.set(
            _interactivity_context_cache_key(context_token),
            {
                "kind": SLACK_PERMISSION_CONTEXT_KIND,
                "integration_id": mapping.integration_id,
                "slack_workspace_id": mapping.slack_workspace_id,
                "channel": mapping.channel,
                "thread_ts": mapping.thread_ts,
                "task_id": str(task_run.task_id),
                "run_id": run_id,
                "request_id": request_id,
                "expected_slack_user_id": target_slack_user_id,
                "default_option_id": default_option["optionId"],
                "reject_option_id": reject_option_id,
                "options": options,
                "tool_label": tool_label,
                "tool_detail": tool_detail,
                "created_at": int(time.time()),
            },
            timeout=SLACK_PERMISSION_CONTEXT_TTL_SECONDS,
        )

        text = f"<@{target_slack_user_id}> the agent needs permission to continue: *{tool_label}*"
        current_permission_mode = _current_permission_mode(task_run, SlackPermissionMode.FULL_AUTO)
        permission_mode_options = [
            _build_permission_mode_option(value, label) for value, label in SlackPermissionMode.choices
        ]
        initial_mode_option = next(
            (option for option in permission_mode_options if option["value"] == current_permission_mode),
            _build_permission_mode_option(SlackPermissionMode.FULL_AUTO, SlackPermissionMode.FULL_AUTO.label),
        )
        card_body = _build_card_body(tool_label, tool_detail)

        blocks: list[dict[str, Any]] = [
            {
                "type": "card",
                "slack_icon": {"type": "icon", "name": "rocket"},
                "title": {
                    "type": "mrkdwn",
                    "text": "Agent approval needed",
                    "verbatim": False,
                },
                "subtitle": {
                    "type": "mrkdwn",
                    "text": f"<@{target_slack_user_id}> can approve or deny this request.",
                    "verbatim": False,
                },
                "body": {
                    "type": "mrkdwn",
                    "text": card_body,
                    "verbatim": False,
                },
                "actions": [
                    {
                        "type": "button",
                        "action_id": SLACK_PERMISSION_ACTION_APPROVE,
                        "style": "primary",
                        "text": {"type": "plain_text", "text": "Approve", "emoji": False},
                        "value": context_token,
                    },
                    {
                        "type": "button",
                        "action_id": SLACK_PERMISSION_ACTION_DENY,
                        "text": {"type": "plain_text", "text": "Deny", "emoji": False},
                        "value": context_token,
                    },
                ],
            }
        ]
        blocks.append(
            {
                "type": "actions",
                "block_id": f"{SLACK_PERMISSION_BLOCK_ID_PREFIX}_config:{context_token}",
                "elements": [
                    {
                        "type": "static_select",
                        "action_id": SLACK_PERMISSION_ACTION_SELECT,
                        "placeholder": {"type": "plain_text", "text": "Permission mode"},
                        "options": permission_mode_options,
                        "initial_option": initial_mode_option,
                    },
                ],
            }
        )

        SlackIntegration(mapping.integration).client.chat_postMessage(
            channel=mapping.channel,
            thread_ts=mapping.thread_ts,
            text=text,
            blocks=blocks,
            metadata={
                "event_type": "posthog_code_permission_request",
                "event_payload": {"context_token": context_token, "run_id": run_id, "request_id": request_id},
            },
        )
        cache.set(dedupe_key, True, timeout=SLACK_PERMISSION_PROMPT_DEDUPE_SECONDS)
        logger.info(
            "slack_permission_prompt_posted",
            run_id=run_id,
            request_id=request_id,
            integration_id=mapping.integration_id,
            channel=mapping.channel,
        )
    except SlackApiError as e:
        slack_error = e.response.get("error") if e.response else None
        response_metadata = e.response.get("response_metadata") if e.response else None
        logger.exception(
            "slack_permission_prompt_post_failed",
            run_id=run_id,
            request_id=request_id,
            integration_id=getattr(mapping, "integration_id", None),
            channel=getattr(mapping, "channel", None),
            slack_error=slack_error,
            response_metadata=response_metadata,
        )
        # The prompt never reached the user, so no one can ever answer it — deny so the
        # agent fails fast instead of hanging until the run's inactivity timeout.
        _deny_unpostable_permission_request(task_run, request_id=request_id, option_id=reject_option_id)
    except Exception:
        logger.exception(
            "slack_permission_prompt_post_failed",
            run_id=run_id,
            request_id=request_id,
            integration_id=getattr(mapping, "integration_id", None),
            channel=getattr(mapping, "channel", None),
        )
    finally:
        cache.delete(inflight_key)
