"""Plain-language progress phases for the Slack agent-design plan block.

The plan shows one line per kind of work, never tool names or tool arguments. A tool call
maps to a phase here, and the relay counts calls per phase for the line's details.
"""

import re
from typing import Any

from posthog.dataclasses import frozen


@frozen
class ProgressPhase:
    key: str
    title: str
    # Singular and plural noun for the call counter, or None for a line without a count.
    counter: tuple[str, str] | None


POSTHOG_DATA = ProgressPhase(key="posthog_data", title="Looking at PostHog data", counter=("query", "queries"))
GETTING_CODE = ProgressPhase(key="getting_code", title="Getting the code", counter=None)
READING_CODE = ProgressPhase(key="reading_code", title="Reading the code", counter=("lookup", "lookups"))
SEARCHING_WEB = ProgressPhase(key="searching_web", title="Searching the web", counter=("lookup", "lookups"))
MAKING_CHANGES = ProgressPhase(key="making_changes", title="Making changes", counter=("edit", "edits"))
RUNNING_CHECKS = ProgressPhase(key="running_checks", title="Running checks", counter=("check", "checks"))
RUNNING_COMMANDS = ProgressPhase(key="running_commands", title="Running commands", counter=("command", "commands"))
PREPARING_FILES = ProgressPhase(key="preparing_files", title="Preparing attachments", counter=("file", "files"))
OPENING_PR = ProgressPhase(key="opening_pr", title="Opening a pull request", counter=None)

PHASES: dict[str, ProgressPhase] = {
    phase.key: phase
    for phase in (
        POSTHOG_DATA,
        GETTING_CODE,
        READING_CODE,
        SEARCHING_WEB,
        MAKING_CHANGES,
        RUNNING_CHECKS,
        RUNNING_COMMANDS,
        PREPARING_FILES,
        OPENING_PR,
    )
}

# Lines the relay shows around the agent's own phases.
UNDERSTANDING_REQUEST = ProgressPhase(key="understanding_request", title="Understanding the request", counter=None)
STARTING_WORKSPACE = ProgressPhase(key="starting_workspace", title="Starting a workspace", counter=None)
RESTORING_WORKSPACE = ProgressPhase(key="restoring_workspace", title="Restoring the workspace", counter=None)
PLAN_TITLE_WORKING = "Working on it"
PLAN_TITLE_DONE = "Done"
PLAN_TITLE_STOPPED = "Stopped"

# Tools that manage the agent's own session. They say nothing about the work, so no line shows them.
_IGNORED_TOOL_MARKERS = (
    "task_summary_update",
    "show_actions",
    "toolsearch",
    "skill",
    "todowrite",
    "taskcreate",
    "taskupdate",
    "taskget",
    "tasklist",
    "taskstop",
    "exitplanmode",
    "enterplanmode",
    "monitor",
    "schedulewakeup",
    "list_mcp_resource",
    "write_stdin",
    "list_agents",
    "sendmessage",
)
_IGNORED_TOOL_NAMES = frozenset({"agent", "task", "wait", "sleep", "spawn_agent", "close_agent", "wait_agent"})
_PR_TOOL_MARKERS = ("git_signed_commit", "git_signed_rewrite", "git_signed_merge", "gh_stack")
_REPO_TOOL_MARKERS = ("clone_repo", "list_repos")
_POSTHOG_MCP_PREFIXES = ("mcp__posthog__", "posthog/")
_EDIT_TOOL_NAMES = frozenset({"edit", "write", "multiedit", "notebookedit", "apply_patch"})
_READ_TOOL_NAMES = frozenset({"read", "grep", "glob", "ls", "notebookread", "view_image"})
_WEB_TOOL_NAMES = frozenset({"websearch", "webfetch", "web_search", "web_fetch"})
_SHELL_TOOL_NAMES = frozenset({"bash", "exec_command", "exec", "shell", "terminal"})

_PR_COMMAND = re.compile(r"\b(gh\s+pr\s+(create|edit|ready)|git\s+(commit|push))\b")
_CHECK_COMMAND = re.compile(
    r"\b(pytest|jest|vitest|playwright|hogli\s+(test|lint|ci)|ruff|mypy|tsc|eslint|oxlint|prettier|"
    r"(pnpm|npm|yarn)\s+(run\s+)?(test|lint|typecheck|typescript:check|build)|"
    r"cargo\s+(test|check|clippy|build)|go\s+(test|vet|build)|make\s+(test|lint|check))\b"
)
_READ_COMMAND = re.compile(
    r"^\s*(cd\s+\S+\s*(&&|;)\s*)?(grep|rg|cat|ls|find|head|tail|wc|tree|jq|less|sed\s+-n|awk|"
    r"git\s+(log|show|diff|status|blame|grep|ls-files))\b"
)


@frozen
class ToolCall:
    """What the classifier needs from one ACP tool call."""

    name: str
    kind: str | None
    command: str | None


def _phase_for_command(command: str) -> ProgressPhase:
    if _PR_COMMAND.search(command):
        return OPENING_PR
    if _CHECK_COMMAND.search(command):
        return RUNNING_CHECKS
    if _READ_COMMAND.match(command):
        return READING_CODE
    return RUNNING_COMMANDS


def phase_for_tool_call(call: ToolCall) -> ProgressPhase | None:
    """The phase a tool call belongs to, or None when the plan should not show it."""
    name = call.name.strip().lower()
    if not name or call.kind == "think":
        return None
    if name in _IGNORED_TOOL_NAMES or any(marker in name for marker in _IGNORED_TOOL_MARKERS):
        return None
    if any(marker in name for marker in _PR_TOOL_MARKERS):
        return OPENING_PR
    if any(marker in name for marker in _REPO_TOOL_MARKERS):
        return GETTING_CODE
    if "artifact" in name:
        return PREPARING_FILES
    if name.startswith(_POSTHOG_MCP_PREFIXES):
        return POSTHOG_DATA
    if name in _WEB_TOOL_NAMES or call.kind == "fetch":
        return SEARCHING_WEB
    if name in _EDIT_TOOL_NAMES or call.kind == "edit":
        return MAKING_CHANGES
    if name in _READ_TOOL_NAMES or call.kind in ("read", "search"):
        return READING_CODE
    if name in _SHELL_TOOL_NAMES or call.kind == "execute":
        return _phase_for_command(call.command or "")
    # Other MCP servers and unknown tools stay out of the plan rather than leak their names.
    return None


def phase_details(phase: ProgressPhase, count: int) -> str | None:
    """The counter line under a phase, such as "7 queries"."""
    if phase.counter is None or count <= 0:
        return None
    singular, plural = phase.counter
    return f"{count} {singular if count == 1 else plural}"


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def tool_call_from_acp_update(update: dict[str, Any]) -> ToolCall | None:
    """Read the tool name, kind and shell command from an ACP ``tool_call``/``tool_call_update``.

    Returns None while a Claude shell call has no command yet: Claude streams the call with an
    empty ``rawInput`` first, and the command decides between reading, checks and a pull request.
    """
    meta = _dict_or_empty(update.get("_meta"))
    claude_tool_name = _dict_or_empty(meta.get("claudeCode")).get("toolName")
    posthog_tool_name = _dict_or_empty(meta.get("posthog")).get("toolName")
    title = update.get("title") if isinstance(update.get("title"), str) else None
    kind = update.get("kind") if isinstance(update.get("kind"), str) else None
    name = claude_tool_name or posthog_tool_name
    if not name and kind in ("execute", "read", "search"):
        # Codex sends shell commands with no tool name and the command as the title.
        return ToolCall(name="exec_command", kind=kind, command=title)
    name = name or title
    if not isinstance(name, str) or not name:
        return None

    raw_input = update.get("rawInput")
    command = raw_input.get("command") if isinstance(raw_input, dict) else None
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    if not isinstance(command, str) or not command:
        command = None
    if command is None and (name.lower() in _SHELL_TOOL_NAMES or kind == "execute"):
        return None
    return ToolCall(name=name, kind=kind, command=command)
