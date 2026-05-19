from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Canonical names of harness-internal tools the agent can call during a run.
# Updated whenever a new tool lands in `scout_harness/tools/`. Order is alphabetical
# so the diff is easy to read when one is added.
HARNESS_INTERNAL_TOOLS: frozenset[str] = frozenset(
    {
        "emit_finding",
        "forget",
        "get_run",
        "remember",
        "search_scratchpad",
        "search_recent_runs",
    }
)


class InvalidAllowedToolsError(ValueError):
    """The skill's `allowed_tools` list is malformed (duplicates, empty strings, wrong type)."""


class UnknownHarnessToolError(LookupError):
    """A skill named a harness-internal tool that does not exist (likely a typo).

    Raised when a name in `allowed_tools` looks like a harness-internal tool — i.e. it
    is a bare identifier with no namespace prefix — but is not in `HARNESS_INTERNAL_TOOLS`.
    Names that look like MCP tools (containing a prefix marker like `:` or `__`) are not
    validated here because the harness cannot enumerate sandbox-provided MCP tools at
    skill-load time; the intersection runs later, at agent-dispatch time.
    """


@dataclass(frozen=True)
class AllowedToolsResolution:
    """Partition of a skill's `allowed_tools` after validation.

    `harness_tools` is the subset that maps to harness-internal tools (validated against
    the registry). `mcp_tool_candidates` is everything else — names that look like MCP
    tool identifiers, validated lazily at dispatch time when the sandbox surface is known.
    Empty `allowed_tools` on the skill means "no narrowing"; the runner exposes the full
    union of harness-internal + MCP-provided tools in that case.
    """

    declared: bool
    harness_tools: frozenset[str]
    mcp_tool_candidates: frozenset[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "declared": self.declared,
            "harness_tools": sorted(self.harness_tools),
            "mcp_tool_candidates": sorted(self.mcp_tool_candidates),
        }


@dataclass(frozen=True)
class EffectiveToolset:
    """Result of intersecting a skill's allowed-tools with the runtime tool surface.

    Computed at agent-dispatch time once the sandbox-provided MCP tool list is known.
    """

    harness_tools: frozenset[str]
    mcp_tools: frozenset[str]

    @property
    def empty(self) -> bool:
        return not self.harness_tools and not self.mcp_tools


def _looks_like_mcp_tool(name: str) -> bool:
    """Heuristic for non-harness names: anything that carries a namespace marker.

    Common MCP tool name shapes (e.g. `mcp__posthog__exec`, `posthog:execute-sql`,
    `team.tool`) all carry a prefix marker. Bare identifiers (`search_runs`) are
    treated as harness-internal candidates and validated against the registry.
    """
    return any(marker in name for marker in ("__", ":", "."))


def validate_and_partition_allowed_tools(allowed_tools: list[str]) -> AllowedToolsResolution:
    """Validate the shape of a skill's `allowed_tools` and partition it.

    Raises `InvalidAllowedToolsError` for malformed entries (non-string, empty, duplicate).
    Raises `UnknownHarnessToolError` if a bare-identifier name is not in
    `HARNESS_INTERNAL_TOOLS` (typo guard).

    Returns `AllowedToolsResolution.declared = False` when `allowed_tools` is empty —
    the runner interprets that as "no narrowing, expose everything."
    """
    if not allowed_tools:
        return AllowedToolsResolution(declared=False, harness_tools=frozenset(), mcp_tool_candidates=frozenset())

    seen: set[str] = set()
    harness: set[str] = set()
    mcp_candidates: set[str] = set()
    unknown_harness: list[str] = []

    for entry in allowed_tools:
        if not isinstance(entry, str):
            raise InvalidAllowedToolsError(f"allowed_tools entry is not a string: {entry!r}")
        name = entry.strip()
        if not name:
            raise InvalidAllowedToolsError("allowed_tools contains an empty or whitespace-only entry")
        if name in seen:
            raise InvalidAllowedToolsError(f"allowed_tools contains a duplicate entry: {name!r}")
        seen.add(name)

        if _looks_like_mcp_tool(name):
            mcp_candidates.add(name)
        elif name in HARNESS_INTERNAL_TOOLS:
            harness.add(name)
        else:
            unknown_harness.append(name)

    if unknown_harness:
        known = ", ".join(sorted(HARNESS_INTERNAL_TOOLS))
        raise UnknownHarnessToolError(
            f"allowed_tools references unknown harness tool(s) {sorted(unknown_harness)!r}; "
            f"known harness tools: [{known}]"
        )

    return AllowedToolsResolution(
        declared=True,
        harness_tools=frozenset(harness),
        mcp_tool_candidates=frozenset(mcp_candidates),
    )


def compute_effective_toolset(
    *,
    resolution: AllowedToolsResolution,
    mcp_tools_available: Iterable[str],
) -> EffectiveToolset:
    """Apply the intersection rule once we know the sandbox-provided MCP surface.

    - `resolution.declared = False` (skill declared no narrowing): expose the full union.
    - `resolution.declared = True`: expose only the names the skill listed, intersected
      with what the runtime actually has. Unknown MCP candidates that the sandbox does
      not provide are silently dropped — agent-dispatch is the source of truth, not the
      skill's intent.
    """
    available_mcp = frozenset(mcp_tools_available)
    if not resolution.declared:
        return EffectiveToolset(harness_tools=HARNESS_INTERNAL_TOOLS, mcp_tools=available_mcp)
    return EffectiveToolset(
        harness_tools=resolution.harness_tools & HARNESS_INTERNAL_TOOLS,
        mcp_tools=resolution.mcp_tool_candidates & available_mcp,
    )
