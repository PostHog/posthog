"""Skills facade: write a team skill from another product.

``upsert_skill`` creates the skill on first call and publishes a new version on every later call,
attributed to the acting user, so a product that documents itself as a skill (a canvas's operations,
for example) can republish without tracking versions.
"""

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.skills.backend.api.skill_services import (
    LLMSkillDuplicateNameConflictError,
    LLMSkillNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
    create_skill,
    get_latest_skills_queryset,
    get_skill_by_name_from_db,
    publish_skill_version,
)


@frozen
class SkillVersion:
    name: str
    version: int
    description: str


class SkillNameTaken(Exception):
    """A skill with this name exists and another owner (or a person) wrote it."""


class SkillPublishConflict(Exception):
    """Another publish changed the skill first, or the skill has no versions left. ``str(error)`` says which."""


def find_skill_name(*, team_id: int, owner: dict[str, str]) -> str | None:
    """The name of the team's live skill whose metadata holds every ``owner`` key and value, if any.

    A product that renames what a skill documents finds its skill here, so it keeps one skill.
    """
    team = Team.objects.get(id=team_id)
    skill = get_latest_skills_queryset(team).filter(metadata__contains=owner).order_by("created_at", "id").first()
    return skill.name if skill is not None else None


def upsert_skill(
    *,
    team_id: int,
    user_id: int,
    name: str,
    description: str,
    body: str,
    metadata: dict | None = None,
    owner: dict[str, str] | None = None,
) -> SkillVersion:
    """Create the skill, or publish a new version of it.

    With ``owner``, an existing skill of that name must hold the same keys and values in its
    metadata. Otherwise this raises ``SkillNameTaken`` and leaves that skill as it is. Raises
    ``SkillPublishConflict`` when a concurrent write wins or the version limit is reached.
    """
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    latest = get_skill_by_name_from_db(team, name)
    try:
        if latest is None:
            skill = create_skill(team, user=user, name=name, description=description, body=body, metadata=metadata)
        else:
            existing_metadata = latest.metadata or {}
            if owner is not None and any(existing_metadata.get(key) != value for key, value in owner.items()):
                raise SkillNameTaken(name)
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
    except (LLMSkillVersionConflictError, LLMSkillDuplicateNameConflictError, LLMSkillNotFoundError) as error:
        raise SkillPublishConflict("Another publish changed this skill at the same time. Try again.") from error
    except LLMSkillVersionLimitError as error:
        raise SkillPublishConflict(
            f"The skill has reached its limit of {error.max_version} versions. Archive it to publish again."
        ) from error
    return SkillVersion(name=skill.name, version=skill.version, description=skill.description)
