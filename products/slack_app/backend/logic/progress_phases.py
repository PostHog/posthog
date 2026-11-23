"""Plain-language progress phases for the Slack agent-design plan block.

A tool call maps to one line per kind of work, never to a tool name or its arguments. A PostHog
tool gets the title the MCP tool catalogue gives it, because some catalogue categories ("Core",
"Query wrappers") are internal names.
"""

import re
from datetime import timedelta
from typing import Any

from posthog.dataclasses import frozen
from posthog.mcp_tool_definitions import get_mcp_tool_definitions
from posthog.slack.channels import clip_text


@frozen
class ProgressPhase:
    key: str
    title: str
    # The noun that counts calls in the line title, such as "queries". None shows no count.
    counter: str | None


# Keys of PostHog lines start with this. The rest of the key is the catalogue title of the tool.
POSTHOG_PHASE_PREFIX = "posthog:"
GETTING_CODE = ProgressPhase(key="getting_code", title="Getting the code", counter=None)
READING_CODE = ProgressPhase(key="reading_code", title="Reading the code", counter="lookups")
SEARCHING_WEB = ProgressPhase(key="searching_web", title="Searching the web", counter="lookups")
MAKING_CHANGES = ProgressPhase(key="making_changes", title="Making changes", counter="edits")
RUNNING_CHECKS = ProgressPhase(key="running_checks", title="Running checks", counter="checks")
RUNNING_COMMANDS = ProgressPhase(key="running_commands", title="Running commands", counter="commands")
PREPARING_FILES = ProgressPhase(key="preparing_files", title="Preparing attachments", counter="files")
OPENING_PR = ProgressPhase(key="opening_pr", title="Opening a pull request", counter=None)
# The relay folds phases past its line limit into this line, so the plan stays short.
OTHER_WORK = ProgressPhase(key="other_work", title="Other work", counter="steps")

PHASES: dict[str, ProgressPhase] = {
    phase.key: phase
    for phase in (
        GETTING_CODE,
        READING_CODE,
        SEARCHING_WEB,
        MAKING_CHANGES,
        RUNNING_CHECKS,
        RUNNING_COMMANDS,
        PREPARING_FILES,
        OPENING_PR,
        OTHER_WORK,
    )
}

# Statuses of agent todo items and of the parent's progress steps, as the statuses Slack draws.
SLACK_STEP_STATUSES = {"pending": "pending", "in_progress": "in_progress", "completed": "complete", "failed": "error"}
PLAN_TITLE_WORKING = "Working on it"
# Placeholder lines that keep a spinner in the plan while no step is open.
PREPARING_LINE_TITLE = "Getting ready"
THINKING_LINE_TITLE = "Thinking"
# The placeholder becomes this when the turn answers without a tool.
ANSWER_LINE_TITLE = "Writing the answer"
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

# The PostHog MCP server runs its tools through one `exec` tool.
_POSTHOG_EXEC_TOOL = "exec"
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
# Output redirection to a file, such as `cat > out.csv`. A `2>` or `>&` redirect only moves a stream.
_WRITE_REDIRECT = re.compile(r"(?<![0-9&>])>>?(?![&>])")
_ACTIVITY_LIMIT = 80
_MAX_AGENT_PLAN_STEPS = 10
_MIN_INTENT_LENGTH = 8

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
_OBJECT_TAG = re.compile(r"<[^>]*>")
_MARKDOWN_MARKS = re.compile(r"[*_`#>]+")
_INTENT_PREFIX = re.compile(
    r"^(?:(?:now|next|then|first|ok|okay|great|good)[,:]?\s+)*"
    r"(?:let me|let's|i'll|i will|i'm going to|i am going to|i need to|i should)\s+",
    re.IGNORECASE,
)


@frozen
class ToolCall:
    """What the classifier needs from one ACP tool call."""

    name: str
    kind: str | None
    command: str | None
    # The plain-language description the agent gave a shell command.
    description: str | None = None
    # The PostHog tool the call runs, or None for a call that is not a PostHog tool call.
    posthog_tool: str | None = None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _short_activity(description: Any) -> str | None:
    if not isinstance(description, str):
        return None
    text = " ".join(description.split()).rstrip(".")
    return clip_text(text, _ACTIVITY_LIMIT) if text else None


def posthog_phase(tool_title: str) -> ProgressPhase:
    """The line for a PostHog tool, titled as the MCP tool catalogue names it."""
    title = clip_text(" ".join(tool_title.split()), _ACTIVITY_LIMIT)
    return ProgressPhase(key=f"{POSTHOG_PHASE_PREFIX}{title}", title=title, counter="calls")


def _phase_for_command(command: str) -> ProgressPhase:
    if _PR_COMMAND.search(command):
        return OPENING_PR
    if _CHECK_COMMAND.search(command):
        return RUNNING_CHECKS
    if _READ_COMMAND.match(command) and not _WRITE_REDIRECT.search(command):
        return READING_CODE
    return RUNNING_COMMANDS


def _phase_for_posthog_tool(tool_name: str) -> ProgressPhase:
    definition = get_mcp_tool_definitions().get(tool_name)
    if definition is None:
        # A tool the catalogue does not know, such as a third-party tool behind the gateway.
        return OTHER_WORK
    return posthog_phase(definition.title)


def phase_for_key(key: str) -> ProgressPhase | None:
    """The phase a signal names, or None for a key this module does not know."""
    if key.startswith(POSTHOG_PHASE_PREFIX) and len(key) > len(POSTHOG_PHASE_PREFIX):
        return posthog_phase(key.removeprefix(POSTHOG_PHASE_PREFIX))
    return PHASES.get(key)


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
    if any(name.startswith(prefix) for prefix in _POSTHOG_MCP_PREFIXES):
        # A PostHog call that only looks up what the server offers is not work on the user's data.
        return _phase_for_posthog_tool(call.posthog_tool) if call.posthog_tool else None
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


def phase_line_title(phase: ProgressPhase, count: int) -> str:
    """The plan line for a phase, such as "Execute SQL query (3 calls)". A single call shows no count.

    The count goes in the title because Slack replaces a step's title on each update, but
    appends its details.
    """
    if phase.counter is None or count <= 1:
        return phase.title
    return f"{phase.title} ({count} {phase.counter})"


def done_plan_title(elapsed: timedelta) -> str:
    """The plan title of a finished turn, such as "Done in 1m 12s"."""
    seconds = max(int(elapsed.total_seconds()), 1)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        duration = f"{hours}h {minutes}m" if minutes else f"{hours}h"
    elif minutes:
        duration = f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
    else:
        duration = f"{seconds}s"
    return f"Done in {duration}"


def intent_from_narrative(text: str) -> str | None:
    """The last sentence the agent wrote before a tool call, as a short activity.

    "Now let me count daily active users for last week." becomes "Count daily active users
    for last week". A question is left out, because it asks the reader and reports nothing.
    """
    plain = _MARKDOWN_MARKS.sub("", _OBJECT_TAG.sub("", text))
    sentences = [sentence.strip() for sentence in _SENTENCE_END.split(plain) if sentence.strip()]
    if not sentences or sentences[-1].endswith("?"):
        return None
    sentence = _INTENT_PREFIX.sub("", sentences[-1]).rstrip(".:!… ")
    if len(sentence) < _MIN_INTENT_LENGTH:
        return None
    return _short_activity(sentence[0].upper() + sentence[1:])


def _posthog_tool(name: str, command: str | None) -> str | None:
    """The PostHog tool a call runs, or None when it only looks up what the server offers."""
    for prefix in _POSTHOG_MCP_PREFIXES:
        if not name.startswith(prefix):
            continue
        tool = name.removeprefix(prefix)
        if tool != _POSTHOG_EXEC_TOOL:
            return tool
        return _exec_call_tool(command)
    return None


def _exec_call_tool(command: str | None) -> str | None:
    """The tool an ``exec`` command such as ``call --json execute-sql {...}`` runs. Other verbs only look up tools."""
    words = (command or "").split()
    if not words or words[0].lower() != "call":
        return None
    tool = next((word for word in words[1:] if not word.startswith("--")), None)
    return tool.lower() if tool else None


def agent_plan_steps(update: dict[str, Any]) -> list[dict[str, str]] | None:
    """The agent's todo list from an ACP ``plan`` update, as ``{"title", "status"}`` steps.

    Claude sends the list its task tools keep and Codex sends its ``update_plan`` steps. The
    statuses become the ones Slack draws. Returns None for any other update.
    """
    if update.get("sessionUpdate") != "plan":
        return None
    entries = update.get("entries")
    steps: list[dict[str, str]] = []
    for entry in entries if isinstance(entries, list) else []:
        entry = _dict_or_empty(entry)
        title = _short_activity(entry.get("content"))
        if title:
            steps.append({"title": title, "status": SLACK_STEP_STATUSES.get(str(entry.get("status")), "pending")})
    return steps[:_MAX_AGENT_PLAN_STEPS]


def tool_call_from_acp_update(update: dict[str, Any]) -> ToolCall | None:
    """Read the tool name, kind, command and description from an ACP ``tool_call``/``tool_call_update``.

    Returns None while a Claude shell or PostHog ``exec`` call has no command yet: Claude streams
    the call with an empty ``rawInput`` first, and the command decides the phase.
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

    raw_input = _dict_or_empty(update.get("rawInput"))
    command = raw_input.get("command")
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    if not isinstance(command, str) or not command:
        command = None
    lowered = name.lower()
    needs_command = lowered in _SHELL_TOOL_NAMES or kind == "execute" or lowered.endswith(f"__{_POSTHOG_EXEC_TOOL}")
    if command is None and needs_command:
        return None
    # Only Claude's shell tool takes a description written for people. A description argument on
    # other tools is content, such as the text of a new dashboard.
    description = _short_activity(raw_input.get("description")) if lowered == "bash" else None
    return ToolCall(
        name=name, kind=kind, command=command, description=description, posthog_tool=_posthog_tool(lowered, command)
    )
