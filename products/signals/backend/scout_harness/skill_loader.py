from __future__ import annotations

from dataclasses import dataclass, field

from posthog.models.team.team import Team

from products.llm_analytics.backend.models.skills import LLMSkill, LLMSkillFile
from products.signals.backend.scout_harness.tool_registry import (
    AllowedToolsResolution,
    validate_and_partition_allowed_tools,
)

# Naming contract for skills that steer a Signals-agent run.
SIGNALS_SCOUT_SKILL_PREFIX = "signals-scout-"


class SkillNotFoundError(LookupError):
    """The team has no skill matching the requested name."""


@dataclass(frozen=True)
class LoadedSkillFile:
    path: str
    content_type: str


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    # Snapshotted onto the run row so a historical run can be reproduced even after re-versioning.
    version: int
    body: str
    description: str
    allowed_tools: list[str]
    files: list[LoadedSkillFile]
    skill_id: str
    # Partition of `allowed_tools` into harness-internal vs MCP candidates, validated at
    # load time. Defaults to the empty / not-declared resolution so existing callers don't
    # need to construct it explicitly during incremental adoption.
    allowed_tools_resolution: AllowedToolsResolution = field(
        default_factory=lambda: AllowedToolsResolution(
            declared=False,
            harness_tools=frozenset(),
            mcp_tool_candidates=frozenset(),
        )
    )


def is_signals_scout_skill(skill: LLMSkill) -> bool:
    return skill.name.startswith(SIGNALS_SCOUT_SKILL_PREFIX)


def load_skill_for_run(team: Team, skill_name: str, *, version: int | None = None) -> LoadedSkill:
    """Resolve a skill on the team's namespace and load its body + file manifest.

    Pass `version=None` to follow-latest. The `signals-scout-*` prefix is not enforced
    here — the management command can hand-trigger any skill on the team.
    """
    # Lazy import: `products.llm_analytics.backend.api` triggers a temporal module load
    # that this package is itself imported from at temporal-worker boot, so a top-level
    # import here cycles. Models only is fine.
    from products.llm_analytics.backend.api.skill_services import get_skill_by_name_from_db

    skill = get_skill_by_name_from_db(team, skill_name, version=version)
    if skill is None:
        raise SkillNotFoundError(
            f"No skill named '{skill_name}' found on team {team.id}"
            + (f" (version {version})" if version is not None else "")
        )
    file_rows = LLMSkillFile.objects.filter(skill=skill).only("path", "content_type").order_by("path")
    raw_allowed_tools = list(skill.allowed_tools or [])
    # Validate at load time so a typo in a skill body fails the run before we spawn a
    # sandbox: unknown harness-internal names raise (typo guard). MCP-shaped names pass
    # through — `allowed_tools` is portable skill metadata that travels with the skill
    # across consumers (scout harness, Claude Code, custom agents). The scout harness
    # itself gates runtime tool access via `posthog_mcp_scopes` at the OAuth/MCP
    # boundary (scope-level), not via this list (tool-level). Downstream consumers
    # that want tool-level narrowing can read `allowed_tools` directly.
    resolution = validate_and_partition_allowed_tools(raw_allowed_tools)
    return LoadedSkill(
        name=skill.name,
        version=skill.version,
        body=skill.body,
        description=skill.description,
        allowed_tools=raw_allowed_tools,
        files=[LoadedSkillFile(path=f.path, content_type=f.content_type) for f in file_rows],
        skill_id=str(skill.id),
        allowed_tools_resolution=resolution,
    )
