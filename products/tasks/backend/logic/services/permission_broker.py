"""Brokering for sandbox agent permission requests.

The sandbox agent session starts with an ``initial_permission_mode`` and raises a
``permission_request`` event for any tool call that mode doesn't already cover. For
runs whose origin surface recorded a broker permission mode on the run state
(``slack_permission_mode``, written at Slack task creation), the relay activity
answers read-only requests here so only decisions that genuinely need a human are
surfaced to the origin (e.g. as a Slack approval card).
"""

import re
import json
import shlex
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.cache import cache

import structlog

from products.tasks.backend.logic.services.agent_command import CommandResult, send_agent_command
from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

POSTHOG_PERMISSION_REQUEST_METHOD = "_posthog/permission_request"
PERMISSION_MODE_STATE_KEY = "slack_permission_mode"
# Must comfortably outlive the run so a replayed relay event can't double-answer.
AUTO_RESPONSE_DEDUPE_SECONDS = 24 * 60 * 60

MCP_TOOL_DEFINITIONS_PATH = Path(settings.BASE_DIR) / "services/mcp/schema/generated-tool-definitions.json"

# Auto-allow only tools with no workspace mutation and no arbitrary network egress.
# WebFetch stays off the list: an injected agent could exfiltrate anything it has
# read by encoding it into an attacker-controlled URL. WebSearch queries only reach
# the search provider, not attacker-chosen endpoints. Agent/Task subagents are safe
# to spawn — each of their tool calls raises its own permission request.
READ_ONLY_NATIVE_PERMISSION_TOOLS = frozenset(
    {
        "Agent",
        "BashOutput",
        "Glob",
        "Grep",
        "LS",
        "NotebookRead",
        "Read",
        "Task",
        "TodoWrite",
        "WebSearch",
    }
)
# Workspace file edits stay sandbox-local until an approved externalization (push,
# PR, artifact delivery), so they're auto-allowed under ask_before_write/full_auto
# but must go to a human when the run promised to be read-only.
WORKSPACE_MUTATION_PERMISSION_TOOLS = frozenset({"Edit", "MultiEdit", "NotebookEdit", "Write"})
# Mirrors products.slack_app.backend.models.SlackPermissionMode.READ_ONLY; the
# broker can't import across the product boundary.
PERMISSION_MODE_READ_ONLY = "read_only"
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
# human approval so a prompt-injected agent cannot mutate external state with
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
        "ls-tree",
        "rev-parse",
        "shortlog",
        "show",
        "status",
    }
)
# Command substitution, environment expansion, process substitution, and bash
# network redirection can smuggle arbitrary execution or secrets (e.g.
# $POSTHOG_PERSONAL_API_KEY) into an otherwise read-only command line.
SHELL_COMMAND_SUBSTITUTION_RE = re.compile(r"\$\(|\$\{|\$[A-Za-z0-9_]|`|<\(|>\(|/dev/(?:tcp|udp)/")
# Flags that make an allowlisted read-only binary execute another program or
# write files (find -exec/-delete/-fprintf, rg --pre, sort --compress-program, ...).
SHELL_UNSAFE_FLAG_RE = re.compile(
    r"(?:^|\s)-{1,2}(?:delete|exec(?:dir)?|exec-batch|ok(?:dir)?|pre|hostname-bin|compress-program|fls|fprint(?:0|f)?)\b"
)
# fd duplication (2>&1, >&2) is harmless; any other `>` can create or truncate a file.
SHELL_FD_DUP_RE = re.compile(r"\d*>&\d+")
SHELL_SEGMENT_SPLIT_RE = re.compile(r"[;\n]|\|\|?|&&?")


def _auto_response_dedupe_key(run_id: str, request_id: str) -> str:
    return f"tasks:permission_auto_response:v1:{run_id}:{request_id}"


def _tool_call_raw_input(tool_call: dict[str, Any]) -> dict[str, Any]:
    raw_input = tool_call.get("rawInput")
    return raw_input if isinstance(raw_input, dict) else {}


def _tool_call_name(tool_call: dict[str, Any]) -> str | None:
    # The wire puts the bare tool name ("Bash", "Read") on _meta.claudeCode.toolName;
    # the top-level field is the fallback. rawInput carries only the tool's input args.
    meta = tool_call.get("_meta")
    claude_code = meta.get("claudeCode") if isinstance(meta, dict) else None
    tool_name = claude_code.get("toolName") if isinstance(claude_code, dict) else None
    if not isinstance(tool_name, str) or not tool_name:
        tool_name = tool_call.get("toolName")
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
        logger.warning("permission_broker_mcp_tool_definitions_load_failed", path=str(MCP_TOOL_DEFINITIONS_PATH))
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
    stripped = SHELL_FD_DUP_RE.sub(" ", command)
    # Any remaining redirect (>, >>, &>, >&file — even a quoted `>`) fails closed
    # to the approval path rather than risking a file write.
    if ">" in stripped:
        return False
    return all(
        _shell_segment_is_read_only(segment) for segment in SHELL_SEGMENT_SPLIT_RE.split(stripped) if segment.strip()
    )


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

    Returns ``{"request_id": str, "tool_call": dict, "tool_name": str | None,
    "options": [{optionId, kind, name}]}`` or ``None`` when the event isn't a
    well-formed permission request.
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
        "tool_name": _tool_call_name(tool_call),
        "options": options,
    }


def _run_state(task_run: "TaskRun") -> dict[str, Any]:
    state = task_run.state
    return state if isinstance(state, dict) else {}


def _broker_permission_mode(task_run: "TaskRun") -> str | None:
    """The broker policy for this run, or ``None`` when the run didn't opt in.

    Runs without a mode on their state (web UI, PostHog AI) keep their existing
    surface-driven approval flow untouched.
    """
    mode = _run_state(task_run).get(PERMISSION_MODE_STATE_KEY)
    return mode if isinstance(mode, str) and mode else None


def _should_auto_allow(task_run: "TaskRun", permission_request: dict[str, Any]) -> bool:
    tool_call = permission_request["tool_call"]
    tool_name = permission_request.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return False
    posthog_tool_name = _posthog_mcp_tool_name(tool_name)
    if posthog_tool_name == "exec":
        command = _tool_call_raw_input(tool_call).get("command")
        return isinstance(command, str) and _posthog_exec_command_should_auto_allow(command)
    if posthog_tool_name is not None:
        return _posthog_tool_is_read_only(posthog_tool_name)
    if tool_name in READ_ONLY_NATIVE_PERMISSION_TOOLS:
        return True
    if tool_name in WORKSPACE_MUTATION_PERMISSION_TOOLS:
        return _broker_permission_mode(task_run) != PERMISSION_MODE_READ_ONLY
    if tool_name == "Bash":
        command = _tool_call_raw_input(tool_call).get("command")
        return isinstance(command, str) and _shell_command_is_read_only(command)
    return False


def _default_allow_option_id(options: list[dict[str, str]]) -> str | None:
    allow_options = [option for option in options if not option["kind"].startswith("reject")]
    default_option = next((option for option in allow_options if option["kind"] == "allow_once"), None)
    if default_option is not None:
        return default_option["optionId"]
    return allow_options[0]["optionId"] if allow_options else None


def send_permission_response(task_run: "TaskRun", *, request_id: str, option_id: str) -> CommandResult:
    """Deliver a permission decision to the run's sandbox, authenticated as the task creator."""
    auth_token = None
    created_by = getattr(getattr(task_run, "task", None), "created_by", None)
    if created_by and getattr(created_by, "id", None):
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    return send_agent_command(
        task_run,
        method="permission_response",
        params={"requestId": request_id, "optionId": option_id},
        auth_token=auth_token,
    )


def try_auto_respond_permission_request(task_run: "TaskRun", permission_request: dict[str, Any]) -> bool:
    """Answer a permission request from the run's recorded permission mode.

    Returns ``True`` when the request was answered (now or previously); ``False``
    hands the decision back to the origin surface for a human prompt.
    """
    if _broker_permission_mode(task_run) is None:
        return False
    if not _should_auto_allow(task_run, permission_request):
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

    result = send_permission_response(task_run, request_id=request_id, option_id=option_id)
    if not result.success:
        logger.warning(
            "permission_broker_auto_allow_failed",
            run_id=run_id,
            request_id=request_id,
            option_id=option_id,
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
    )
    return True
