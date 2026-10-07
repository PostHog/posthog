"""Tool-name lists a run carries into its sandbox's PostHog MCP entry.

A run's state can name tools to hide (`mcp_exclude_tools`) and tools to allow
(`mcp_allowed_tools`). Both ride as comma-separated headers, so a name is only
kept when it is a plausible tool name and the list stays under the header cap.
"""

import re
from collections.abc import Sequence
from typing import Any

_MCP_TOOL_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_MCP_TOOL_NAMES = 32
MCP_EXCLUDE_TOOLS_STATE_KEY = "mcp_exclude_tools"
MCP_ALLOWED_TOOLS_STATE_KEY = "mcp_allowed_tools"


def sanitize_mcp_tool_names(names: Sequence[str] | None) -> list[str]:
    if not names:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for name in names:
        token = name.strip().lower()
        if not _MCP_TOOL_NAME.fullmatch(token) or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
        if len(cleaned) >= MAX_MCP_TOOL_NAMES:
            break
    return cleaned


def _mcp_tool_names_from_state(state: dict[str, Any] | None, key: str) -> list[str]:
    raw = (state or {}).get(key)
    if not isinstance(raw, list):
        return []
    return sanitize_mcp_tool_names([name for name in raw if isinstance(name, str)])


def mcp_exclude_tools_from_state(state: dict[str, Any] | None) -> list[str]:
    return _mcp_tool_names_from_state(state, MCP_EXCLUDE_TOOLS_STATE_KEY)


def mcp_allowed_tools_from_state(state: dict[str, Any] | None) -> list[str]:
    """The tools a run's brief allowed. Empty means no allowlist, so the catalog is served whole."""
    return _mcp_tool_names_from_state(state, MCP_ALLOWED_TOOLS_STATE_KEY)
