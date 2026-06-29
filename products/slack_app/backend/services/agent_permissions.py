import time
import uuid
import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from django.core.cache import cache

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegration

logger = structlog.get_logger(__name__)

SLACK_PERMISSION_CONTEXT_KIND = "task_permission_request"
SLACK_PERMISSION_CONTEXT_TTL_SECONDS = 15 * 60
SLACK_PERMISSION_PROMPT_DEDUPE_SECONDS = SLACK_PERMISSION_CONTEXT_TTL_SECONDS
SLACK_PERMISSION_PROMPT_INFLIGHT_SECONDS = 30
SLACK_PERMISSION_BODY_MAX_LENGTH = 2900

SLACK_PERMISSION_BLOCK_ID_PREFIX = "posthog_code_permission"
SLACK_PERMISSION_ACTION_APPROVE = "posthog_code_permission_approve"
SLACK_PERMISSION_ACTION_DENY = "posthog_code_permission_deny"
SLACK_PERMISSION_ACTION_SELECT = "posthog_code_permission_select"
POSTHOG_PERMISSION_REQUEST_METHOD = "_posthog/permission_request"
SlackToolEffectClass = Literal["read", "internal_write", "customer_facing"]

_EFFECT_CLASS_FIELDS = (
    "effectClass",
    "effect_class",
    "toolEffectClass",
    "tool_effect_class",
    "slackEffectClass",
    "slack_effect_class",
)
_EFFECT_CLASS_ALIASES: dict[str, SlackToolEffectClass] = {
    "read": "read",
    "read_only": "read",
    "readonly": "read",
    "internal_write": "internal_write",
    "internalwrite": "internal_write",
    "write": "internal_write",
    "customer_facing": "customer_facing",
    "customerfacing": "customer_facing",
    "external": "customer_facing",
    "outbound_external": "customer_facing",
    "outboundexternal": "customer_facing",
}
_READ_TOOL_NAMES = frozenset({"glob", "grep", "ls", "read", "view", "notebookread", "todoread"})
_WRITE_TOOL_MARKERS = (
    "write",
    "edit",
    "patch",
    "delete",
    "create",
    "update",
    "mcp__",
    "curl",
    "post ",
    "put ",
    "patch ",
    "delete ",
    "git commit",
    "git push",
    "gh pr create",
)
_CUSTOMER_FACING_MARKERS = (
    "customer",
    "external",
    "user-facing",
    "customer-facing",
    "email",
    "mailgun",
    "sendgrid",
    "sms",
    "twilio",
    "zendesk",
    "intercom",
    "support ticket",
    "reply to customer",
    "send to customer",
)
_SLACK_DELIVERY_MARKERS = (
    "slack_file",
    "slack_message",
    "slack_canvas",
    "chat.postmessage",
    "chat_update",
    "chat_postmessage",
    "living_artifacts",
)


@dataclass(frozen=True)
class SlackPermissionBrokerDecision:
    effect_class: SlackToolEffectClass
    requires_human_approval: bool
    reason: str


def _interactivity_context_cache_key(context_token: str) -> str:
    # The interactivity dispatcher already resolves ownership through this shared context namespace.
    token_hash = hashlib.sha256(context_token.encode("utf-8")).hexdigest()
    return f"posthog_code_repo_picker_ctx:{token_hash}"


def _permission_prompt_dedupe_key(run_id: str, request_id: str) -> str:
    return f"posthog_code:permission_prompt:v1:{run_id}:{request_id}"


def _permission_prompt_inflight_key(run_id: str, request_id: str) -> str:
    return f"posthog_code:permission_prompt_inflight:v1:{run_id}:{request_id}"


def _tool_call_raw_input(tool_call: dict[str, Any]) -> dict[str, Any]:
    raw_input = tool_call.get("rawInput")
    return raw_input if isinstance(raw_input, dict) else {}


def _tool_call_name(tool_call: dict[str, Any]) -> str | None:
    tool_name = _tool_call_raw_input(tool_call).get("toolName")
    return tool_name if isinstance(tool_name, str) and tool_name else None


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


def _extract_tool_summary(tool_call: dict[str, Any]) -> tuple[str, str | None]:
    raw_input = _tool_call_raw_input(tool_call)
    title = tool_call.get("title") if isinstance(tool_call.get("title"), str) else None
    tool_name = _tool_call_name(tool_call)
    description = raw_input.get("description") if isinstance(raw_input.get("description"), str) else None
    command = raw_input.get("command") if isinstance(raw_input.get("command"), str) else None

    label = description or title or tool_name or "Run tool"
    detail = command
    return _truncate_slack_text(label, 150), _truncate_slack_text(detail, 1200) if detail else None


def _tool_call_text(tool_call: dict[str, Any]) -> str:
    raw_input = tool_call.get("rawInput")
    raw_input = raw_input if isinstance(raw_input, dict) else {}
    parts: list[str] = []
    for value in (
        tool_call.get("title"),
        tool_call.get("name"),
        raw_input.get("toolName"),
        raw_input.get("description"),
        raw_input.get("command"),
    ):
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return " ".join(parts).lower()


def _tool_name(tool_call: dict[str, Any]) -> str:
    raw_input = tool_call.get("rawInput")
    raw_input = raw_input if isinstance(raw_input, dict) else {}
    tool_name = raw_input.get("toolName") or tool_call.get("name") or tool_call.get("title")
    return tool_name.lower() if isinstance(tool_name, str) else ""


def _command_text(tool_call: dict[str, Any]) -> str:
    raw_input = tool_call.get("rawInput")
    raw_input = raw_input if isinstance(raw_input, dict) else {}
    command = raw_input.get("command")
    return command.lower().strip() if isinstance(command, str) else ""


def _normalize_declared_effect_class(value: Any) -> SlackToolEffectClass | None:
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _EFFECT_CLASS_ALIASES.get(key)


def _declared_tool_effect_class(tool_call: dict[str, Any]) -> SlackToolEffectClass | None:
    raw_input = tool_call.get("rawInput")
    raw_input = raw_input if isinstance(raw_input, dict) else {}

    containers: list[dict[str, Any]] = [tool_call, raw_input]
    for nested_key in ("metadata", "annotations"):
        nested_tool = tool_call.get(nested_key)
        if isinstance(nested_tool, dict):
            containers.append(nested_tool)
        nested_input = raw_input.get(nested_key)
        if isinstance(nested_input, dict):
            containers.append(nested_input)

    for container in containers:
        for field in _EFFECT_CLASS_FIELDS:
            effect_class = _normalize_declared_effect_class(container.get(field))
            if effect_class is not None:
                return effect_class
    return None


def _command_looks_read_only(command: str) -> bool:
    if not command:
        return False
    if any(marker in command for marker in _WRITE_TOOL_MARKERS):
        return False
    read_prefixes = (
        "cat ",
        "cd ",
        "find ",
        "gh pr view",
        "git diff",
        "git log",
        "git show",
        "git status",
        "grep ",
        "head ",
        "ls",
        "pwd",
        "rg ",
        "sed -n",
        "tail ",
        "which ",
    )
    return command.startswith(read_prefixes)


def _classify_tool_effect(task_run: Any, tool_call: dict[str, Any]) -> SlackToolEffectClass:
    declared_effect_class = _declared_tool_effect_class(tool_call)
    if declared_effect_class is not None:
        return declared_effect_class

    text = _tool_call_text(tool_call)
    is_customer_facing_channel = bool((getattr(task_run, "state", None) or {}).get("slack_is_ext_shared_channel"))

    tool_name = _tool_name(tool_call)
    command = _command_text(tool_call)
    if tool_name in _READ_TOOL_NAMES and (not command or _command_looks_read_only(command)):
        return "read"
    if _command_looks_read_only(command):
        return "read"

    if any(marker in text for marker in _CUSTOMER_FACING_MARKERS):
        return "customer_facing"
    if is_customer_facing_channel and any(marker in text for marker in _SLACK_DELIVERY_MARKERS):
        return "customer_facing"

    has_write_marker = any(marker in text for marker in _WRITE_TOOL_MARKERS)
    if is_customer_facing_channel and has_write_marker:
        return "customer_facing"
    if is_customer_facing_channel and not command:
        return "customer_facing"
    if has_write_marker:
        return "internal_write"
    if is_customer_facing_channel:
        return "customer_facing"
    return "internal_write"


def _permission_broker_decision(
    *,
    task_run: Any,
    tool_call: dict[str, Any],
    autonomy_tier: str,
) -> SlackPermissionBrokerDecision:
    effect_class = _classify_tool_effect(task_run, tool_call)
    if effect_class == "customer_facing":
        return SlackPermissionBrokerDecision(effect_class, True, "customer_facing_requires_approval")
    if effect_class == "read":
        return SlackPermissionBrokerDecision(effect_class, False, "read_allowed")
    if autonomy_tier == "full_auto":
        return SlackPermissionBrokerDecision(effect_class, False, "full_auto_internal_write")
    return SlackPermissionBrokerDecision(effect_class, True, "tier_requires_approval")


def _build_permission_body(tool_label: str, tool_detail: str | None) -> str:
    body = tool_label
    if tool_detail:
        body = f"{body}\n\nCommand:\n```{tool_detail}```"
    return _truncate_slack_text(body, SLACK_PERMISSION_BODY_MAX_LENGTH)


def _permission_option_label(option: dict[str, Any]) -> str:
    kind = option.get("kind")
    if kind == "allow_once":
        return "Allow once"
    if kind == "allow_always":
        return "Always allow this command"
    if kind == "reject_once":
        return "Deny once"
    name = option.get("name")
    return _truncate_slack_text(name, 75) if isinstance(name, str) and name.strip() else "Use this permission"


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
                "name": name if isinstance(name, str) else _permission_option_label(option),
                "label": _permission_option_label(option),
            }
        )
    return normalized


def _allow_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed = [option for option in options if not option["kind"].startswith("reject")]
    return allowed or options


def _reject_option_id(options: list[dict[str, str]]) -> str | None:
    for option in options:
        if option["kind"].startswith("reject"):
            return option["optionId"]
    return None


def _send_broker_permission_response(
    *,
    task_run: Any,
    mapping: Any,
    target_slack_user_id: str,
    request_id: str,
    option_id: str,
    decision: SlackPermissionBrokerDecision,
) -> bool:
    from products.slack_app.backend.api import resolve_slack_user  # noqa: PLC0415
    from products.tasks.backend.temporal.client import signal_task_permission_response  # noqa: PLC0415

    slack = SlackIntegration(mapping.integration)
    actor_context = resolve_slack_user(
        slack,
        mapping.integration,
        target_slack_user_id,
        mapping.channel,
        mapping.thread_ts,
        post_feedback=False,
    )
    if actor_context is None:
        logger.info(
            "slack_permission_broker_actor_unresolved",
            run_id=str(task_run.id),
            request_id=request_id,
            slack_user_id=target_slack_user_id,
        )
        return False

    actor = actor_context.user
    try:
        signal_task_permission_response(
            task_run.workflow_id,
            request_id=request_id,
            option_id=option_id,
            actor_user_id=actor.id,
            actor_slack_user_id=target_slack_user_id,
            effect_class=decision.effect_class,
            broker_reason=decision.reason,
        )
    except Exception:
        logger.warning(
            "slack_permission_broker_signal_failed",
            run_id=str(task_run.id),
            request_id=request_id,
            option_id=option_id,
            effect_class=decision.effect_class,
            reason=decision.reason,
            actor_user_id=actor.id,
            exc_info=True,
        )
        return False
    logger.info(
        "slack_permission_broker_response_signaled",
        run_id=str(task_run.id),
        request_id=request_id,
        option_id=option_id,
        effect_class=decision.effect_class,
        reason=decision.reason,
        actor_user_id=actor.id,
    )
    return True


def _build_autonomy_tier_option(value: str, label: str) -> dict[str, Any]:
    return {"text": {"type": "plain_text", "text": label}, "value": value}


def _initial_autonomy_tier(task_run: Any, fallback: str) -> str:
    state = getattr(task_run, "state", None)
    if not isinstance(state, dict):
        return fallback
    tier = state.get("slack_autonomy_tier")
    return tier if isinstance(tier, str) else fallback


def _permission_request_payload(event_data: dict[str, Any]) -> dict[str, Any] | None:
    if event_data.get("type") == "permission_request":
        return event_data

    notification = event_data.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != POSTHOG_PERMISSION_REQUEST_METHOD:
        return None

    params = notification.get("params")
    return params if isinstance(params, dict) else None


def _permission_request_from_event(event_data: dict[str, Any]) -> dict[str, Any] | None:
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


def handle_slack_permission_request_for_task_run(task_run: Any, event_data: dict[str, Any]) -> None:
    """Route Slack permission requests through the workflow-owned permission broker."""
    permission_request = _permission_request_from_event(event_data)
    if permission_request is None:
        return

    request_id = permission_request["request_id"]
    run_id = str(task_run.id)
    mapping = _slack_mapping_for_task_run(task_run)
    if mapping is None:
        logger.info("slack_permission_prompt_no_mapping", run_id=run_id, request_id=request_id)
        return

    post_slack_permission_request_for_task_run(
        task_run, event_data, permission_request=permission_request, mapping=mapping
    )


def post_slack_permission_request_for_task_run(
    task_run: Any,
    event_data: dict[str, Any],
    *,
    permission_request: dict[str, Any] | None = None,
    mapping: Any = None,
) -> None:
    """Post a Slack approval prompt for a sandbox permission_request event."""
    permission_request = permission_request or _permission_request_from_event(event_data)
    if permission_request is None:
        return

    from products.slack_app.backend.models import SlackAutonomyTier

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

        target_slack_user_id = mapping.latest_actor_slack_user_id or mapping.mentioning_slack_user_id
        if not target_slack_user_id:
            logger.info("slack_permission_prompt_no_target_user", run_id=run_id, request_id=request_id)
            return

        options = permission_request["options"]
        allow_options = _allow_options(options)
        default_option = next((option for option in allow_options if option["kind"] == "allow_once"), allow_options[0])
        reject_option_id = _reject_option_id(options)
        if reject_option_id is None:
            logger.info("slack_permission_prompt_no_reject_option", run_id=run_id, request_id=request_id)
            return

        tool_label, tool_detail = _extract_tool_summary(permission_request["tool_call"])
        current_autonomy_tier = _initial_autonomy_tier(task_run, SlackAutonomyTier.ASK_BEFORE_WRITE)
        broker_decision = _permission_broker_decision(
            task_run=task_run,
            tool_call=permission_request["tool_call"],
            autonomy_tier=current_autonomy_tier,
        )
        if not broker_decision.requires_human_approval:
            if _send_broker_permission_response(
                task_run=task_run,
                mapping=mapping,
                target_slack_user_id=target_slack_user_id,
                request_id=request_id,
                option_id=default_option["optionId"],
                decision=broker_decision,
            ):
                cache.set(dedupe_key, True, timeout=SLACK_PERMISSION_PROMPT_DEDUPE_SECONDS)
                return
            logger.info(
                "slack_permission_broker_fell_back_to_prompt",
                run_id=run_id,
                request_id=request_id,
                effect_class=broker_decision.effect_class,
                reason=broker_decision.reason,
            )

        context_token = uuid.uuid4().hex
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
                "effect_class": broker_decision.effect_class,
                "created_at": int(time.time()),
            },
            timeout=SLACK_PERMISSION_CONTEXT_TTL_SECONDS,
        )

        text = f"<@{target_slack_user_id}> the agent needs permission to continue: *{tool_label}*"
        autonomy_tier_options = [
            _build_autonomy_tier_option(value, label) for value, label in SlackAutonomyTier.choices
        ]
        initial_autonomy_option = next(
            (option for option in autonomy_tier_options if option["value"] == current_autonomy_tier),
            _build_autonomy_tier_option(SlackAutonomyTier.ASK_BEFORE_WRITE, SlackAutonomyTier.ASK_BEFORE_WRITE.label),
        )
        permission_body = _build_permission_body(tool_label, tool_detail)

        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":rocket: *Agent approval needed*\n<@{target_slack_user_id}> can approve or deny this request.",
                    "verbatim": False,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": permission_body,
                    "verbatim": False,
                },
            },
            {
                "type": "actions",
                "block_id": f"{SLACK_PERMISSION_BLOCK_ID_PREFIX}_decision:{context_token}",
                "elements": [
                    {
                        "type": "button",
                        "action_id": SLACK_PERMISSION_ACTION_DENY,
                        "text": {"type": "plain_text", "text": "Deny", "emoji": False},
                        "value": context_token,
                    },
                    {
                        "type": "button",
                        "action_id": SLACK_PERMISSION_ACTION_APPROVE,
                        "style": "primary",
                        "text": {"type": "plain_text", "text": "Approve", "emoji": False},
                        "value": context_token,
                    },
                ],
            },
        ]
        blocks.append(
            {
                "type": "actions",
                "block_id": f"{SLACK_PERMISSION_BLOCK_ID_PREFIX}_config:{context_token}",
                "elements": [
                    {
                        "type": "static_select",
                        "action_id": SLACK_PERMISSION_ACTION_SELECT,
                        "placeholder": {"type": "plain_text", "text": "Approval config"},
                        "options": autonomy_tier_options,
                        "initial_option": initial_autonomy_option,
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
            effect_class=broker_decision.effect_class,
            reason=broker_decision.reason,
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
