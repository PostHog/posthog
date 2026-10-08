"""Skills facade: write a team skill from another product.

``upsert_skill`` creates the skill on first call and publishes a new version on every later call,
attributed to the acting user, so a product that documents itself as a skill (a canvas's operations,
for example) can republish without tracking versions.
"""

from dataclasses import dataclass

from posthog.models import Team, User

from products.skills.backend.api.skill_services import create_skill, get_skill_by_name_from_db, publish_skill_version


@dataclass(frozen=True)
class SkillVersion:
    name: str
    version: int
    description: str


def upsert_skill(
    *, team_id: int, user_id: int, name: str, description: str, body: str, metadata: dict | None = None
) -> SkillVersion:
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    latest = get_skill_by_name_from_db(team, name)
    if latest is None:
        skill = create_skill(team, user=user, name=name, description=description, body=body, metadata=metadata)
    else:
        skill = publish_skill_version(
            team,
            user=user,
            skill_name=name,
            body=body,
            description=description,
            metadata=metadata,
            base_version=latest.version,
            version_description="Republished",
        )
    return SkillVersion(name=skill.name, version=skill.version, description=skill.description)
