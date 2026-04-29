from __future__ import annotations

from dataclasses import dataclass

from posthog.models.team.team import Team

from products.llm_analytics.backend.api.skill_services import get_skill_by_name_from_db
from products.llm_analytics.backend.models.skills import LLMSkill, LLMSkillFile

# Naming contract for skills that steer a Signals-agent run.
SIGNALS_AGENT_SKILL_PREFIX = "signals-agent-"


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


def is_signals_agent_skill(skill: LLMSkill) -> bool:
    return skill.name.startswith(SIGNALS_AGENT_SKILL_PREFIX)


def load_skill_for_run(team: Team, skill_name: str, *, version: int | None = None) -> LoadedSkill:
    """Resolve a skill on the team's namespace and load its body + file manifest.

    Pass `version=None` to follow-latest. The `signals-agent-*` prefix is not enforced
    here — the management command can hand-trigger any skill on the team.
    """
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
