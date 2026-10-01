"""Plain-language progress phases for the Slack agent-design plan block.

The plan shows one line per kind of work, never tool names or tool arguments. A tool call
maps to a phase here, and the relay counts calls per phase for the line's title.

PostHog work gets one line per product, and a SQL query goes on the line for the table it
reads first, so a data question shows "Querying events" rather than one line for all of it.

While a line is open it can also say what runs now: the description Claude writes for a
shell command, else the last sentence the agent wrote before the call.
"""

import re
from datetime import timedelta
from typing import Any

from posthog.dataclasses import frozen


@frozen
class ProgressPhase:
    key: str
    title: str
    # Singular and plural noun for the call counter in the line title, or None for no count.
    counter: tuple[str, str] | None


_LOOKUPS = ("lookup", "lookups")

_QUERIES = ("query", "queries")

POSTHOG_EVENTS = ProgressPhase(key="posthog_events", title="Querying events", counter=_QUERIES)
POSTHOG_SESSIONS = ProgressPhase(key="posthog_sessions", title="Querying sessions", counter=_QUERIES)
POSTHOG_PEOPLE = ProgressPhase(key="posthog_people", title="Looking up people and cohorts", counter=_LOOKUPS)
POSTHOG_SCHEMA = ProgressPhase(key="posthog_schema", title="Checking what data exists", counter=_LOOKUPS)
POSTHOG_WEB = ProgressPhase(key="posthog_web", title="Checking web analytics", counter=_LOOKUPS)
POSTHOG_DASHBOARDS = ProgressPhase(key="posthog_dashboards", title="Checking dashboards and insights", counter=_LOOKUPS)
POSTHOG_ERRORS = ProgressPhase(key="posthog_errors", title="Checking error tracking", counter=_LOOKUPS)
POSTHOG_REPLAYS = ProgressPhase(key="posthog_replays", title="Checking session recordings", counter=_LOOKUPS)
POSTHOG_FLAGS = ProgressPhase(key="posthog_flags", title="Checking feature flags and experiments", counter=_LOOKUPS)
POSTHOG_LOGS = ProgressPhase(key="posthog_logs", title="Checking logs and traces", counter=_LOOKUPS)
POSTHOG_AI = ProgressPhase(key="posthog_ai", title="Checking AI observability", counter=_LOOKUPS)
POSTHOG_SURVEYS = ProgressPhase(key="posthog_surveys", title="Checking surveys", counter=_LOOKUPS)
POSTHOG_WAREHOUSE = ProgressPhase(key="posthog_warehouse", title="Checking the data warehouse", counter=_LOOKUPS)
# For a PostHog tool no product line covers yet. Add a line above when one shows up often.
POSTHOG_OTHER = ProgressPhase(key="posthog_other", title="Checking PostHog", counter=_LOOKUPS)
GETTING_CODE = ProgressPhase(key="getting_code", title="Getting the code", counter=None)
READING_CODE = ProgressPhase(key="reading_code", title="Reading the code", counter=_LOOKUPS)
SEARCHING_WEB = ProgressPhase(key="searching_web", title="Searching the web", counter=_LOOKUPS)
MAKING_CHANGES = ProgressPhase(key="making_changes", title="Making changes", counter=("edit", "edits"))
RUNNING_CHECKS = ProgressPhase(key="running_checks", title="Running checks", counter=("check", "checks"))
RUNNING_COMMANDS = ProgressPhase(key="running_commands", title="Running commands", counter=("command", "commands"))
PREPARING_FILES = ProgressPhase(key="preparing_files", title="Preparing attachments", counter=("file", "files"))
OPENING_PR = ProgressPhase(key="opening_pr", title="Opening a pull request", counter=None)
# The relay folds phases past its line limit into this line, so the plan stays short.
OTHER_WORK = ProgressPhase(key="other_work", title="Other work", counter=("step", "steps"))

PHASES: dict[str, ProgressPhase] = {
    phase.key: phase
    for phase in (
        POSTHOG_EVENTS,
        POSTHOG_SESSIONS,
        POSTHOG_PEOPLE,
        POSTHOG_SCHEMA,
        POSTHOG_WEB,
        POSTHOG_DASHBOARDS,
        POSTHOG_ERRORS,
        POSTHOG_REPLAYS,
        POSTHOG_FLAGS,
        POSTHOG_LOGS,
        POSTHOG_AI,
        POSTHOG_SURVEYS,
        POSTHOG_WAREHOUSE,
        POSTHOG_OTHER,
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

SETUP_LINE_TITLE = "Getting ready"
# The setup line becomes this when the turn answers without a tool.
ANSWER_LINE_TITLE = "Writing the answer"
PLAN_TITLE_WORKING = "Working on it"
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

# The PostHog MCP server exposes its tools through one `exec` tool: `call <tool> <json>` runs a
# tool, and the other verbs only look up what the server offers.
_POSTHOG_EXEC_TOOL = "exec"
_POSTHOG_LOOKUP_VERBS = frozenset({"search", "info", "schema", "tools", "learn"})
# First match wins, so a narrower prefix sits above a broader one that shares its start.
_POSTHOG_TOOL_PREFIXES: tuple[tuple[str, ProgressPhase], ...] = (
    ("query-error", POSTHOG_ERRORS),
    ("query-session", POSTHOG_REPLAYS),
    ("error-", POSTHOG_ERRORS),
    ("session-recording", POSTHOG_REPLAYS),
    ("vision-", POSTHOG_REPLAYS),
    ("inline-scan", POSTHOG_REPLAYS),
    ("dashboard", POSTHOG_DASHBOARDS),
    ("insight", POSTHOG_DASHBOARDS),
    ("notebook", POSTHOG_DASHBOARDS),
    ("feature-flag", POSTHOG_FLAGS),
    ("create-feature", POSTHOG_FLAGS),
    ("delete-feature", POSTHOG_FLAGS),
    ("flag-value", POSTHOG_FLAGS),
    ("experiment", POSTHOG_FLAGS),
    ("early-access", POSTHOG_FLAGS),
    ("logs-", POSTHOG_LOGS),
    ("apm-", POSTHOG_LOGS),
    ("llma-", POSTHOG_AI),
    ("llm-", POSTHOG_AI),
    ("ai-observability", POSTHOG_AI),
    ("survey", POSTHOG_SURVEYS),
    ("data-warehouse", POSTHOG_WAREHOUSE),
    ("external-data", POSTHOG_WAREHOUSE),
    ("warehouse", POSTHOG_WAREHOUSE),
    ("managed-warehouse", POSTHOG_WAREHOUSE),
    ("data-modeling", POSTHOG_WAREHOUSE),
    ("data-quality", POSTHOG_WAREHOUSE),
    ("batch-export", POSTHOG_WAREHOUSE),
    ("persons", POSTHOG_PEOPLE),
    ("cohort", POSTHOG_PEOPLE),
    ("group", POSTHOG_PEOPLE),
    ("read-data-schema", POSTHOG_SCHEMA),
    ("event-definition", POSTHOG_SCHEMA),
    ("property-definition", POSTHOG_SCHEMA),
    ("action", POSTHOG_SCHEMA),
    ("web-analytics", POSTHOG_WEB),
    ("heatmap", POSTHOG_WEB),
    ("query-", POSTHOG_EVENTS),
)
_POSTHOG_SQL_TOOL = "execute-sql"

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
_ACTIVITY_LIMIT = 80
_MIN_INTENT_LENGTH = 8

_SQL_ESCAPED_WHITESPACE = re.compile(r"\\[ntr]")
_SQL_TABLE = re.compile(r"\b(?:from|join)\s+([a-z_][\w.]*)")
# The first table a query reads decides its line. A table no entry names is a warehouse table.
_SQL_TABLES: dict[str, ProgressPhase] = {
    "events": POSTHOG_EVENTS,
    "sessions": POSTHOG_SESSIONS,
    "raw_sessions": POSTHOG_SESSIONS,
    "persons": POSTHOG_PEOPLE,
    "person": POSTHOG_PEOPLE,
    "person_distinct_ids": POSTHOG_PEOPLE,
    "groups": POSTHOG_PEOPLE,
    "cohort_people": POSTHOG_PEOPLE,
    "logs": POSTHOG_LOGS,
}
# PostHog objects the agent reads through `system.*` tables. First match wins.
_SQL_SYSTEM_TABLE_PREFIXES: tuple[tuple[str, ProgressPhase], ...] = (
    ("system.information_schema", POSTHOG_SCHEMA),
    ("system.insight", POSTHOG_DASHBOARDS),
    ("system.dashboard", POSTHOG_DASHBOARDS),
    ("system.notebook", POSTHOG_DASHBOARDS),
    ("system.feature_flag", POSTHOG_FLAGS),
    ("system.experiment", POSTHOG_FLAGS),
    ("system.survey", POSTHOG_SURVEYS),
    ("system.cohort", POSTHOG_PEOPLE),
    ("system.", POSTHOG_SCHEMA),
    ("information_schema", POSTHOG_SCHEMA),
)

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
    # The plain-language description the agent gave a shell command, when it gave one.
    description: str | None = None
    # The SQL a PostHog query runs. What it reads decides the line.
    sql: str | None = None


def _phase_for_command(command: str) -> ProgressPhase:
    if _PR_COMMAND.search(command):
        return OPENING_PR
    if _CHECK_COMMAND.search(command):
        return RUNNING_CHECKS
    if _READ_COMMAND.match(command):
        return READING_CODE
    return RUNNING_COMMANDS


def _posthog_tool_name(tool_name: str, command: str | None) -> str | None:
    """The PostHog tool a call runs, or None when it only looks up what the server offers."""
    if tool_name != _POSTHOG_EXEC_TOOL:
        return tool_name
    words = [word for word in (command or "").split() if not word.startswith("--")]
    if not words or words[0].lower() in _POSTHOG_LOOKUP_VERBS:
        return None
    if words[0].lower() == "call":
        return words[1].lower() if len(words) > 1 else ""
    return ""


def _phase_for_sql(sql: str) -> ProgressPhase:
    tables = _SQL_TABLE.findall(_SQL_ESCAPED_WHITESPACE.sub(" ", sql).lower())
    if not tables:
        return POSTHOG_OTHER
    table = tables[0]
    for prefix, phase in _SQL_SYSTEM_TABLE_PREFIXES:
        if table.startswith(prefix):
            return phase
    return _SQL_TABLES.get(table, POSTHOG_WAREHOUSE)


def _phase_for_posthog_tool(tool_name: str, sql: str | None) -> ProgressPhase:
    if tool_name == _POSTHOG_SQL_TOOL:
        return _phase_for_sql(sql or "")
    for prefix, phase in _POSTHOG_TOOL_PREFIXES:
        if tool_name.startswith(prefix):
            return phase
    return POSTHOG_OTHER


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
    for prefix in _POSTHOG_MCP_PREFIXES:
        if name.startswith(prefix):
            posthog_tool = _posthog_tool_name(name.removeprefix(prefix), call.command)
            return _phase_for_posthog_tool(posthog_tool, call.sql) if posthog_tool is not None else None
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


def phase_line_title(phase: ProgressPhase, count: int, activity: str | None = None) -> str:
    """The plan line for a phase, such as "Querying events (7 queries)".

    ``activity`` replaces the counter while the line is open, so the reader sees what runs now.
    The line carries everything in its title because Slack replaces a step's title on each
    task_update but appends its details and output to the text it already shows.
    """
    if activity:
        return f"{phase.title}: {activity}"
    if phase.counter is None or count <= 0:
        return phase.title
    singular, plural = phase.counter
    return f"{phase.title} ({count} {singular if count == 1 else plural})"


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


def _posthog_sql(name: str, command: str | None, raw_input: dict[str, Any]) -> str | None:
    """The SQL of a PostHog SQL call, or None for any other call."""
    for prefix in _POSTHOG_MCP_PREFIXES:
        if name.startswith(prefix):
            if _posthog_tool_name(name.removeprefix(prefix), command) != _POSTHOG_SQL_TOOL:
                return None
            query = raw_input.get("query")
            return query if isinstance(query, str) and query else command
    return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _short_activity(description: Any) -> str | None:
    if not isinstance(description, str):
        return None
    text = " ".join(description.split()).rstrip(".")
    if not text:
        return None
    return text if len(text) <= _ACTIVITY_LIMIT else text[: _ACTIVITY_LIMIT - 1] + "…"


def tool_call_from_acp_update(update: dict[str, Any]) -> ToolCall | None:
    """Read the tool name, kind, command and description from an ACP ``tool_call``/``tool_call_update``.

    Returns None while a Claude shell, PostHog or SQL call has no input yet: Claude streams the
    call with an empty ``rawInput`` first, and the input decides the phase.
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
    # Only Claude's shell tool writes its description for people. A description argument on
    # other tools is content, such as the text of a dashboard the agent creates.
    description = _short_activity(raw_input.get("description")) if lowered == "bash" else None
    sql = _posthog_sql(lowered, command, raw_input)
    if sql is None and lowered.endswith(_POSTHOG_SQL_TOOL):
        return None
    return ToolCall(name=name, kind=kind, command=command, description=description, sql=sql)
