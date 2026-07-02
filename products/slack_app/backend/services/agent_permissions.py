import re
import json
import time
import uuid
import shlex
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.cache import cache

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegration

logger = structlog.get_logger(__name__)

SLACK_PERMISSION_CONTEXT_KIND = "task_permission_request"
SLACK_PERMISSION_CONTEXT_TTL_SECONDS = 15 * 60
SLACK_PERMISSION_PROMPT_DEDUPE_SECONDS = SLACK_PERMISSION_CONTEXT_TTL_SECONDS
SLACK_PERMISSION_PROMPT_INFLIGHT_SECONDS = 30
SLACK_CARD_BODY_MAX_LENGTH = 200

SLACK_PERMISSION_BLOCK_ID_PREFIX = "posthog_code_permission"
SLACK_PERMISSION_ACTION_APPROVE = "posthog_code_permission_approve"
SLACK_PERMISSION_ACTION_DENY = "posthog_code_permission_deny"
SLACK_PERMISSION_ACTION_SELECT = "posthog_code_permission_select"
POSTHOG_PERMISSION_REQUEST_METHOD = "_posthog/permission_request"
MCP_TOOL_DEFINITIONS_PATH = Path(settings.BASE_DIR) / "services/mcp/schema/generated-tool-definitions.json"

SAFE_NATIVE_PERMISSION_TOOLS = frozenset(
    {
        "Agent",
        "BashOutput",
        "Edit",
        "Glob",
        "Grep",
        "LS",
        "MultiEdit",
        "NotebookEdit",
        "NotebookRead",
        "Read",
        "Task",
        "TodoWrite",
        "WebFetch",
        "WebSearch",
        "Write",
    }
)
POSTHOG_EXEC_READ_ONLY_COMMANDS = frozenset({"info", "schema", "search", "tools"})
DESTRUCTIVE_SHELL_PATTERNS = (
    re.compile(r"(^|[;&|])\s*(?:sudo\s+)?(?:rm|rmdir|unlink|shred)\b", re.IGNORECASE),
    re.compile(r"(^|[;&|])\s*(?:sudo\s+)?find\b[^;&|]*\s-delete\b", re.IGNORECASE),
    re.compile(
        r"(^|[;&|])\s*(?:sudo\s+)?git\s+(?:clean\b|reset\s+--hard\b|branch\s+-D\b|push\b[^;&|]*--delete\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(^|[;&|])\s*(?:sudo\s+)?gh\s+(?:repo\s+delete\b|api\b[^;&|]*(?:-X|--method)\s+DELETE\b)",
        re.IGNORECASE,
    ),
)
# Auto-allow only commands positively identified as read-only: anything else
# (network writes via curl, interpreters, package managers) must go through
# Slack approval so a prompt-injected agent cannot mutate external state with
# the sandbox credentials.
READ_ONLY_SHELL_COMMANDS = frozenset(
    {
        "basename",
        "cat",
        "cd",
        "column",
        "comm",
        "cut",
        "date",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "file",
        "find",
        "grep",
        "head",
        "hostname",
        "id",
        "jq",
        "ls",
        "md5sum",
        "nl",
        "od",
        "printf",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "sha256sum",
        "sort",
        "stat",
        "strings",
        "tail",
        "tr",
        "tree",
        "uname",
        "uniq",
        "wc",
        "which",
        "whoami",
        "xxd",
    }
)
GIT_READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "blame",
        "branch",
        "cat-file",
        "describe",
        "diff",
        "grep",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "rev-parse",
        "shortlog",
        "show",
        "status",
    }
)
# Command substitution, process substitution, and bash network redirection can
# smuggle arbitrary execution into an otherwise read-only command line.
SHELL_COMMAND_SUBSTITUTION_RE = re.compile(r"\$\(|`|<\(|>\(|/dev/(?:tcp|udp)/")
# Flags that make an allowlisted read-only binary execute another program
# (find -exec/-delete, rg --pre, sort --compress-program, ...).
SHELL_UNSAFE_FLAG_RE = re.compile(
    r"(?:^|\s)-{1,2}(?:delete|exec(?:dir)?|exec-batch|ok(?:dir)?|pre|hostname-bin|compress-program)\b"
)
SHELL_FD_REDIRECT_RE = re.compile(r"\d*>&\d*|&>>?")
SHELL_SEGMENT_SPLIT_RE = re.compile(r"[;\n]|\|\|?|&&?")


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


def _posthog_mcp_tool_name(tool_name: str) -> str | None:
    parts = tool_name.split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp" or not parts[1].startswith("posthog"):
        return None
    return parts[2]


def _posthog_exec_inner_tool_name(command: str) -> str | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    if not parts or parts[0] != "call":
        return None

    tool_index = 1
    while tool_index < len(parts) and parts[tool_index].startswith("--"):
        tool_index += 1
    return parts[tool_index] if tool_index < len(parts) else None


def _posthog_exec_command_should_auto_allow(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    if not parts:
        return False
    if parts[0] in POSTHOG_EXEC_READ_ONLY_COMMANDS:
        return True

    inner_tool_name = _posthog_exec_inner_tool_name(command)
    return inner_tool_name is not None and _posthog_tool_is_read_only(inner_tool_name)


@lru_cache(maxsize=1)
def _mcp_tool_annotations() -> dict[str, dict[str, Any]]:
    try:
        with MCP_TOOL_DEFINITIONS_PATH.open() as definitions_file:
            definitions = json.load(definitions_file)
    except (OSError, json.JSONDecodeError):
        logger.warning("slack_permission_mcp_tool_definitions_load_failed", path=str(MCP_TOOL_DEFINITIONS_PATH))
        return {}

    if not isinstance(definitions, dict):
        return {}

    annotations_by_tool: dict[str, dict[str, Any]] = {}
    for tool_name, definition in definitions.items():
        if not isinstance(tool_name, str) or not isinstance(definition, dict):
            continue
        annotations = definition.get("annotations")
        if isinstance(annotations, dict):
            annotations_by_tool[tool_name] = annotations
    return annotations_by_tool


def _posthog_tool_is_read_only(tool_name: str) -> bool:
    # Fail closed: a tool without a readOnlyHint annotation stays on the approval path.
    annotations = _mcp_tool_annotations().get(tool_name)
    if annotations is None:
        return False
    return annotations.get("readOnlyHint") is True


def _shell_command_is_destructive(command: str) -> bool:
    return any(pattern.search(command) for pattern in DESTRUCTIVE_SHELL_PATTERNS)


def _shell_segment_is_read_only(segment: str) -> bool:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return False
    if not tokens:
        return True
    command_name = tokens[0]
    if command_name == "git":
        return len(tokens) >= 2 and tokens[1] in GIT_READ_ONLY_SUBCOMMANDS
    return command_name in READ_ONLY_SHELL_COMMANDS


def _shell_command_is_read_only(command: str) -> bool:
    if not command.strip():
        return False
    if _shell_command_is_destructive(command):
        return False
    if SHELL_COMMAND_SUBSTITUTION_RE.search(command) or SHELL_UNSAFE_FLAG_RE.search(command):
        return False
    stripped = SHELL_FD_REDIRECT_RE.sub(" ", command)
    return all(
        _shell_segment_is_read_only(segment) for segment in SHELL_SEGMENT_SPLIT_RE.split(stripped) if segment.strip()
    )


def _permission_request_should_auto_allow(permission_request: dict[str, Any]) -> bool:
    tool_call = permission_request["tool_call"]
    tool_name = _tool_call_name(tool_call)
    if tool_name is None:
        return False
    posthog_tool_name = _posthog_mcp_tool_name(tool_name)
    if posthog_tool_name == "exec":
        command = _tool_call_raw_input(tool_call).get("command")
        return isinstance(command, str) and _posthog_exec_command_should_auto_allow(command)
    if posthog_tool_name is not None:
        return _posthog_tool_is_read_only(posthog_tool_name)
    if tool_name in SAFE_NATIVE_PERMISSION_TOOLS:
        return True
    if tool_name == "Bash":
        command = _tool_call_raw_input(tool_call).get("command")
        return isinstance(command, str) and _shell_command_is_read_only(command)
    return False


def _default_allow_option_id(options: list[dict[str, str]]) -> str | None:
    allow_options = _allow_options(options)
    default_option = next((option for option in allow_options if option["kind"] == "allow_once"), None)
    if default_option is not None:
        return default_option["optionId"]
    return allow_options[0]["optionId"] if allow_options else None


def _slack_mapping_for_task_run(task_run: Any) -> Any:
    from products.slack_app.backend.models import SlackThreadTaskMapping

    return (
        SlackThreadTaskMapping.objects.select_related("integration")
        .filter(task_run=task_run)
        .order_by("-updated_at")
        .first()
    )


def _auto_approve_slack_permission_request(task_run: Any, permission_request: dict[str, Any], mapping: Any) -> bool:
    request_id = permission_request["request_id"]
    run_id = str(task_run.id)
    dedupe_key = _permission_prompt_dedupe_key(run_id, request_id)
    if cache.get(dedupe_key):
        return True

    option_id = _default_allow_option_id(permission_request["options"])
    if option_id is None:
        logger.info("slack_permission_auto_allow_no_allow_option", run_id=run_id, request_id=request_id)
        return False

    from products.tasks.backend.logic.services.agent_command import send_agent_command
    from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token

    auth_token = None
    created_by = getattr(getattr(task_run, "task", None), "created_by", None)
    if created_by and getattr(created_by, "id", None):
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    result = send_agent_command(
        task_run,
        method="permission_response",
        params={"requestId": request_id, "optionId": option_id},
        auth_token=auth_token,
    )
    if not result.success:
        logger.warning(
            "slack_permission_auto_allow_failed",
            run_id=run_id,
            request_id=request_id,
            option_id=option_id,
            integration_id=getattr(mapping, "integration_id", None),
            channel=getattr(mapping, "channel", None),
            status_code=result.status_code,
            error=result.error,
        )
        return False

    cache.set(dedupe_key, True, timeout=SLACK_PERMISSION_PROMPT_DEDUPE_SECONDS)
    logger.info(
        "slack_permission_auto_allowed",
        run_id=run_id,
        request_id=request_id,
        option_id=option_id,
        integration_id=getattr(mapping, "integration_id", None),
        channel=getattr(mapping, "channel", None),
    )
    return True


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


def _build_card_body(tool_label: str, tool_detail: str | None) -> str:
    body = tool_label
    if tool_detail:
        body = f"{body}. Command: {tool_detail}"
    return _truncate_slack_text(body, SLACK_CARD_BODY_MAX_LENGTH)


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
    """Auto-approve read-only or sandbox-local permission requests and prompt for everything else."""
    permission_request = _permission_request_from_event(event_data)
    if permission_request is None:
        return

    request_id = permission_request["request_id"]
    run_id = str(task_run.id)
    mapping = _slack_mapping_for_task_run(task_run)
    if mapping is None:
        logger.info("slack_permission_prompt_no_mapping", run_id=run_id, request_id=request_id)
        return

    if _permission_request_should_auto_allow(permission_request) and _auto_approve_slack_permission_request(
        task_run, permission_request, mapping
    ):
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
                "created_at": int(time.time()),
            },
            timeout=SLACK_PERMISSION_CONTEXT_TTL_SECONDS,
        )

        tool_label, tool_detail = _extract_tool_summary(permission_request["tool_call"])
        text = f"<@{target_slack_user_id}> the agent needs permission to continue: *{tool_label}*"
        current_autonomy_tier = _initial_autonomy_tier(task_run, SlackAutonomyTier.ASK_BEFORE_WRITE)
        autonomy_tier_options = [
            _build_autonomy_tier_option(value, label) for value, label in SlackAutonomyTier.choices
        ]
        initial_autonomy_option = next(
            (option for option in autonomy_tier_options if option["value"] == current_autonomy_tier),
            _build_autonomy_tier_option(SlackAutonomyTier.ASK_BEFORE_WRITE, SlackAutonomyTier.ASK_BEFORE_WRITE.label),
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
