"""The MCP tool catalogue as a scout sees it.

A scout run holds an OAuth token minted from a scope preset in `posthog/temporal/oauth.py`,
so the tools it can call are the catalogued tools whose required scopes that token carries.
This module answers that question for every tool, which is what a per-scout tool picker needs
before any of it can be configured.
"""

from __future__ import annotations

from functools import lru_cache

from posthog.dataclasses import frozen
from posthog.mcp_tool_definitions import McpToolDefinition, get_mcp_tool_definitions
from posthog.temporal.oauth import (
    SCOUT_GRANTABLE_WRITE_SCOPES,
    SCOUT_SCOPE_PRESETS,
    ScoutScopePreset,
    resolve_scopes,
    scout_scope_posture,
)


@frozen
class ScoutToolEntry:
    definition: McpToolDefinition
    # Every required scope is inside the widest posture a scout run can be dispatched with.
    holdable: bool
    # Required scopes the baseline `signals_scout` posture does not carry. On a holdable tool
    # these name what the scout has to be granted, or which preset it has to opt into. On a
    # tool that is not holdable they name what no scout can reach.
    missing_scopes: tuple[str, ...]


@frozen
class ScoutScopePresetEntry:
    name: ScoutScopePreset
    scopes: tuple[str, ...]


@frozen
class ScoutToolCatalogue:
    tools: tuple[ScoutToolEntry, ...]
    presets: tuple[ScoutScopePresetEntry, ...]
    grantable_write_scopes: tuple[str, ...]


def _preset_scopes(preset: ScoutScopePreset, *, extra_write_scopes: tuple[str, ...] = ()) -> frozenset[str]:
    return frozenset(resolve_scopes(scout_scope_posture(preset, list(extra_write_scopes))))


@lru_cache(maxsize=1)
def get_scout_tool_catalogue() -> ScoutToolCatalogue:
    """The catalogue every scout is measured against.

    Derived from committed definition files and from the scope sets in
    `posthog/temporal/oauth.py`, so it is the same for every project and is built once per
    process. A superseded tool is left out: its definition names the successors that replaced
    it, and a picker that offered it would configure a scout for a tool on its way out.
    """
    baseline = _preset_scopes("signals_scout")
    widest = _preset_scopes(
        "signals_scout_reports",
        extra_write_scopes=tuple(sorted(SCOUT_GRANTABLE_WRITE_SCOPES)),
    )

    tools = []
    for definition in get_mcp_tool_definitions().values():
        if definition.is_superseded:
            continue
        required = set(definition.required_scopes)
        tools.append(
            ScoutToolEntry(
                definition=definition,
                holdable=required <= widest,
                missing_scopes=tuple(sorted(required - baseline)),
            )
        )

    return ScoutToolCatalogue(
        tools=tuple(sorted(tools, key=lambda entry: entry.definition.name)),
        presets=tuple(
            ScoutScopePresetEntry(name=preset, scopes=tuple(sorted(_preset_scopes(preset))))
            for preset in SCOUT_SCOPE_PRESETS
        ),
        grantable_write_scopes=tuple(sorted(SCOUT_GRANTABLE_WRITE_SCOPES)),
    )
