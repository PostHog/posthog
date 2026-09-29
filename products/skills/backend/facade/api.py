from posthog.dataclasses import frozen
from posthog.models import Team

from products.skills.backend.api.skill_services import get_skill_by_name_from_db

_MAX_SKILL_PROMPT_BODY_BYTES = 64 * 1024


@frozen
class SkillPrompt:
    body: str
    version: int


def get_skill_prompt(*, team_id: int, skill_name: str) -> SkillPrompt | None:
    team = Team.objects.filter(pk=team_id).first()
    if team is None:
        return None

    skill = get_skill_by_name_from_db(team, skill_name)
    if skill is None or not skill.body or len(skill.body.encode("utf-8")) > _MAX_SKILL_PROMPT_BODY_BYTES:
        return None

    if skill.files.exists():
        return None

    return SkillPrompt(body=skill.body, version=skill.version)
