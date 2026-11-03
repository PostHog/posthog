from __future__ import annotations

import json
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

from products.skills.backend.models.skills import LLMSkillFile

if TYPE_CHECKING:
    from posthog.models.team.team import Team

    from products.skills.backend.models.skills import LLMSkill


class SkillNotFoundError(LookupError):
    """The team has no active version of the requested skill."""


@frozen
class LoadedSkillFile:
    path: str
    content_type: str


def load_agent_skill_row(team: Team, skill_name: str, *, version: int | None = None) -> LLMSkill:
    # The API service imports Temporal activities, which also load agent definitions.
    from products.skills.backend.api.skill_services import get_skill_by_name_from_db  # noqa: PLC0415

    skill = get_skill_by_name_from_db(team, skill_name, version=version)
    if skill is None:
        raise SkillNotFoundError(
            f"No skill named '{skill_name}' found on team {team.id}"
            + (f" (version {version})" if version is not None else "")
        )
    return skill


@frozen
class AgentSkill:
    name: str
    version: int
    body: str
    description: str
    allowed_tools: list[str]
    files: list[LoadedSkillFile]
    skill_id: str

    @classmethod
    def from_row(cls, skill: LLMSkill) -> AgentSkill:
        return cls(
            name=skill.name,
            version=skill.version,
            body=skill.body,
            description=skill.description,
            allowed_tools=list(skill.allowed_tools or []),
            files=[
                LoadedSkillFile(path=file.path, content_type=file.content_type)
                for file in LLMSkillFile.objects.filter(skill=skill).only("path", "content_type").order_by("path")
            ],
            skill_id=str(skill.id),
        )

    @classmethod
    def load(cls, team: Team, skill_name: str, *, version: int | None = None) -> AgentSkill:
        return cls.from_row(load_agent_skill_row(team, skill_name, version=version))

    def research_instructions(self) -> str:
        reference = json.dumps({"skill_name": self.name, "version": self.version})
        manifest = "\n".join(f"- {file.path}" for file in self.files)
        return (
            f"Selected skill: {reference}\n\n{self.body}\n\n"
            "Read bundled references through `skill-file-get` with the same skill_name and version. "
            "Keep that version for this run. A skill does not grant tools or change permissions.\n"
            f"{manifest}"
        )
