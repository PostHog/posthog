from urllib.parse import quote

from django.conf import settings

import requests
from pydantic import BaseModel

from posthog.utils import get_instance_region

from products.skills.backend.facade.api import SkillPrompt, get_skill_prompt


class _StoredSkill(BaseModel):
    body: str
    version: int
    files: list[object]
    body_next_offset: int | None


def get_audit_skill(skill_name: str) -> SkillPrompt | None:
    if get_instance_region() != "EU":
        return get_skill_prompt(team_id=2, skill_name=skill_name)

    token = settings.GROWTH_ACCOUNT_AUDIT_US_API_KEY
    if not token:
        raise RuntimeError("US audit skill access is not configured")
    response = requests.get(
        f"https://us.posthog.com/api/projects/2/llm_skills/name/{quote(skill_name, safe='')}/",
        headers={"Authorization": f"Bearer {token}"},
        params={"body_length": 65536},
        timeout=(3, 10),
        allow_redirects=False,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    skill = _StoredSkill.model_validate(response.json(), strict=True)
    if skill.files or skill.body_next_offset is not None or not skill.body.strip() or len(skill.body.encode()) > 65536:
        return None
    return SkillPrompt(body=skill.body, version=skill.version)
