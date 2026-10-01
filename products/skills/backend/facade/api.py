from typing import TYPE_CHECKING

from posthog.dataclasses import frozen
from posthog.models import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.skills.backend.api.skill_services import get_skill_by_name_from_db

if TYPE_CHECKING:
    from posthog.models import User

_MAX_SKILL_PROMPT_BODY_BYTES = 64 * 1024


@frozen
class SkillPrompt:
    body: str
    version: int


def get_skill_prompt(*, team_id: int, skill_name: str, user: "User | None") -> SkillPrompt | None:
    team = Team.objects.filter(pk=team_id, project__is_pending_deletion=False).first()
    if team is None or user is None:
        return None

    skill = get_skill_by_name_from_db(team, skill_name)
    if skill is None or not skill.body or len(skill.body.encode("utf-8")) > _MAX_SKILL_PROMPT_BODY_BYTES:
        return None

    access_control = UserAccessControl(user, team=team)
    if not access_control.has_project_access or not access_control.check_access_level_for_object(skill, "viewer"):
        return None

    if skill.files.exists():
        return None

    return SkillPrompt(body=skill.body, version=skill.version)
