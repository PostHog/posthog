from __future__ import annotations

from dataclasses import dataclass

from posthog.models.team.team import Team

from products.ai_observability.backend.models.skills import LLMSkill, LLMSkillFile

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
    # Portable skill metadata — opaque to the harness. Logged on spawn for observability,
    # not consulted at runtime. Downstream consumers (e.g. Claude Code) may read this list
    # to narrow their own tool exposure; the scout harness itself gates via
    # `posthog_mcp_scopes` at the OAuth/MCP boundary (scope-level), not tool-level.
    allowed_tools: list[str]
    files: list[LoadedSkillFile]
    skill_id: str


def is_signals_scout_skill(skill: LLMSkill) -> bool:
    return skill.name.startswith(SIGNALS_SCOUT_SKILL_PREFIX)


def load_skill_for_run(team: Team, skill_name: str, *, version: int | None = None) -> LoadedSkill:
    """Resolve a skill on the team's namespace and load its body + file manifest.

    Pass `version=None` to follow-latest. The `signals-scout-*` prefix is not enforced
    here — the management command can hand-trigger any skill on the team.
    """
    # Lazy import: `products.ai_observability.backend.api` triggers a temporal module load
    # that this package is itself imported from at temporal-worker boot, so a top-level
    # import here cycles. Models only is fine.
    from products.ai_observability.backend.api.skill_services import get_skill_by_name_from_db

    skill = get_skill_by_name_from_db(team, skill_name, version=version)
    if skill is None:
        raise SkillNotFoundError(
            f"No skill named '{skill_name}' found on team {team.id}"
            + (f" (version {version})" if version is not None else "")
        )
    file_rows = LLMSkillFile.objects.filter(skill=skill).only("path", "content_type").order_by("path")
    return LoadedSkill(
        name=skill.name,
        version=skill.version,
        body=skill.body,
        description=skill.description,
        allowed_tools=list(skill.allowed_tools or []),
        files=[LoadedSkillFile(path=f.path, content_type=f.content_type) for f in file_rows],
        skill_id=str(skill.id),
    )
