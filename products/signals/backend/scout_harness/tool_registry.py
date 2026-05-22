from __future__ import annotations

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
    Names that look like MCP tools (containing a prefix marker like `:` or `__`) are
    not validated against the runtime MCP registry here: `allowed_tools` is portable
    skill metadata that travels with the skill across consumers (scout harness,
    Claude Code, custom agents), and the canonical MCP surface for any given
    consumer is only known at that consumer's dispatch time.
    """


@dataclass(frozen=True)
class AllowedToolsResolution:
    """Partition of a skill's `allowed_tools` after validation.

    `harness_tools` is the subset that maps to harness-internal tools (validated against
    the registry). `mcp_tool_candidates` is everything else — names that look like MCP
    tool identifiers; these are kept as the skill author wrote them and surfaced to
    downstream consumers. `allowed_tools` itself is portable skill metadata: the scout
    harness gates runtime tool access via `posthog_mcp_scopes` at the OAuth/MCP
    boundary (scope-level), while other consumers (e.g. Claude Code) may read this
    list directly to narrow their own tool exposure (tool-level).

    Empty `allowed_tools` on the skill means "no narrowing intent declared".
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
