"""The MCP tool catalogue as a scout sees it.

A scout run holds an OAuth token minted from a scope preset in `posthog/temporal/oauth.py`,
so the tools it can call are the catalogued tools whose required scopes that token carries.
This module answers that question for every tool, which is what a per-scout tool picker needs
before any of it can be configured.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Literal

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.mcp_tool_definitions import McpToolDefinition, get_mcp_tool_definitions
from posthog.temporal.oauth import (
    SCOUT_GRANTABLE_WRITE_SCOPES,
    SCOUT_SCOPE_PRESETS,
    ScoutScopePreset,
    resolve_scopes,
    scout_scope_posture,
)

if TYPE_CHECKING:
    from posthog.models.team.team import Team


def scout_tool_access_enabled(team: Team) -> bool:
    try:
        return (
            posthoganalytics.feature_enabled(
                "scouts-tool-access",
                str(team.uuid),
                groups={"project": str(team.uuid)},
                group_properties={"project": {"id": team.parent_team_id or team.id, "uuid": str(team.uuid)}},
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception as error:
        capture_exception(error)
        return False


SCOUT_RUN_CONTEXT_TOOLS = frozenset(
    {
        "scout-emit-report",
        "scout-edit-report",
        "scout-emit-signal",
        "scout-scratchpad-search",
        "scout-scratchpad-remember",
        "scout-scratchpad-forget",
        "scout-notes-list",
        "scout-metadata-get",
        "scout-project-profile-get",
        "scout-record-output",
        "scout-check-record-result",
    }
)


@frozen
class ScoutToolPresetEntry:
    name: Literal["read_only", "support_notes"]
    label: str
    tools: tuple[str, ...]


@frozen
class ScoutToolEntry:
    definition: McpToolDefinition
    # The widest posture a scout run can be dispatched with satisfies every required scope.
    holdable: bool
    # Required scopes the baseline `signals_scout` posture does not carry. On a holdable tool
    # these name what the scout has to be granted, or which preset it has to opt into. On a
    # tool that is not holdable they include every scope no scout can reach, next to any
    # grantable ones.
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
    tool_presets: tuple[ScoutToolPresetEntry, ...]


def _preset_scopes(preset: ScoutScopePreset, *, extra_write_scopes: list[str] | None = None) -> frozenset[str]:
    return frozenset(resolve_scopes(scout_scope_posture(preset, extra_write_scopes or [])))


def _satisfies(scopes: frozenset[str], required_scope: str) -> bool:
    # A write scope also satisfies the read scope on the same object, in the MCP server
    # (`hasScope` in services/mcp/src/lib/api.ts) and in `posthog/permissions.py`. Scout tokens
    # carry `signal_scout_internal:write` and never its read scope, so plain set membership
    # would report tools a scout calls as out of reach.
    if required_scope in scopes:
        return True
    return required_scope.endswith(":read") and f"{required_scope.removesuffix(':read')}:write" in scopes


@lru_cache(maxsize=1)
def get_scout_tool_catalogue() -> ScoutToolCatalogue:
    """The catalogue every scout is measured against.

    Derived from committed definition files and from the scope sets in
    `posthog/temporal/oauth.py`, so it is the same for every project and is built once per
    process. A superseded tool is left out: its definition names the successors that replaced
    it, and a picker that offered it would configure a scout for a tool on its way out.
    """
    baseline = _preset_scopes("signals_scout")
    widest = _preset_scopes("signals_scout_reports", extra_write_scopes=sorted(SCOUT_GRANTABLE_WRITE_SCOPES))

    tools = []
    for definition in get_mcp_tool_definitions().values():
        if definition.is_superseded:
            continue
        required = set(definition.required_scopes)
        tools.append(
            ScoutToolEntry(
                definition=definition,
                holdable=all(_satisfies(widest, scope) for scope in required),
                missing_scopes=tuple(sorted(scope for scope in required if not _satisfies(baseline, scope))),
            )
        )

    read_tools = tuple(
        sorted(
            entry.definition.name
            for entry in tools
            if entry.holdable and entry.definition.read_only and entry.definition.name not in SCOUT_RUN_CONTEXT_TOOLS
        )
    )
    return ScoutToolCatalogue(
        tools=tuple(sorted(tools, key=lambda entry: entry.definition.name)),
        presets=tuple(
            ScoutScopePresetEntry(name=preset, scopes=tuple(sorted(_preset_scopes(preset))))
            for preset in SCOUT_SCOPE_PRESETS
        ),
        grantable_write_scopes=tuple(sorted(SCOUT_GRANTABLE_WRITE_SCOPES)),
        tool_presets=(
            ScoutToolPresetEntry(name="read_only", label="Read only", tools=read_tools),
            ScoutToolPresetEntry(
                name="support_notes",
                label="Support notes",
                tools=tuple(sorted((*read_tools, "conversations-tickets-notes-create"))),
            ),
        ),
    )
