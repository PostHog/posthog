"""Parsing for the single-exec PostHog MCP tool, shared by the backend and the eval harness.

In single-exec mode the agent reaches every PostHog tool through one ``exec`` call, so the tool the
agent meant is only in the command string.
"""

import json
from typing import Any

INFO_SYNTHETIC_PREFIX = "__info__:"
"""Synthetic name assigned when ``exec {command: "info <tool>"}`` is unwrapped.

Lets scorers treat the single-exec CLI's ``info <tool>`` and Claude Code's
``ToolSearch(select:mcp__posthog__<tool>)`` as interchangeable
"tool schema loaded" signals via a stable namespaced name.
"""


def normalize_tool_name(name: str | None) -> str:
    """Strip the Claude-Code MCP namespace prefix from a tool name.

    Claude Code surfaces MCP tools as ``mcp__<server>__<tool>``. Scorers
    think in bare tool names like ``query-retention``; normalising here
    keeps the public API simple.
    """
    if not name:
        return ""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


_CALL_FLAGS = frozenset({"--json", "--confirm", "--no-skills"})


def parse_exec_command(command: str) -> tuple[str, dict[str, Any]] | None:
    """Split a CLI-style ``exec`` command string into ``(virtual_name, input)``.

    Recognised shapes (produced by single-exec mode where the agent talks to
    the PostHog MCP through one ``exec`` tool):
      - ``"info <tool>"``                    → ``("__info__:<tool>", {})``
      - ``"call [--json] [--confirm] [--no-skills] <tool> <json>"`` → ``("<tool>", parsed_json)``

    Returns ``None`` for anything else (``search``, ``tools``, ``schema``,
    malformed) so callers can fall through to the raw ``exec`` representation.
    """
    stripped = command.strip()
    if not stripped:
        return None

    head, _, rest = stripped.partition(" ")
    head = head.lower()

    if head == "info":
        tool = rest.strip().split(None, 1)[0] if rest.strip() else ""
        if tool:
            return (f"{INFO_SYNTHETIC_PREFIX}{tool}", {})
        return None

    if head == "call":
        rest = rest.strip()
        flag, _, remainder = rest.partition(" ")
        while flag in _CALL_FLAGS:
            rest = remainder.lstrip()
            flag, _, remainder = rest.partition(" ")
        if not rest:
            return None
        tool, _, json_part = rest.partition(" ")
        tool = tool.strip()
        if not tool:
            return None
        json_part = json_part.strip()
        parsed: dict[str, Any] = {}
        if json_part:
            try:
                decoded = json.loads(json_part)
                if isinstance(decoded, dict):
                    parsed = decoded
            except json.JSONDecodeError:
                parsed = {}
        return (tool, parsed)

    return None
