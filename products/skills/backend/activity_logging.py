from typing import TYPE_CHECKING, Any

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.utils import activity_storage

from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

if TYPE_CHECKING:
    from posthog.models import Team, User

SKILL_ACTIVITY_SCOPE = "LLMSkill"

# Fields a publish can change on the logical skill. `body` is recorded as changed without its
# content, because a body can be up to 1 MB and the history only needs to say that it moved.
_PUBLISHED_FIELDS = ("description", "license", "compatibility", "allowed_tools", "metadata", "category")


def skill_activity_item_id(team: "Team", skill_name: str) -> str | None:
    """The id of the skill's first live version row.

    Every version is its own row and a rename rewrites the name on all of them, so neither a
    version id nor the name stays the same for the life of a skill. The first row does.
    """
    first_id = (
        LLMSkill.objects.filter(team=team, name=skill_name, deleted=False)
        .order_by("version", "created_at", "id")
        .values_list("id", flat=True)
        .first()
    )
    return str(first_id) if first_id is not None else None


def log_skill_activity(
    *,
    team: "Team",
    user: "User | None",
    skill_name: str,
    activity: str,
    item_id: str | None = None,
    changes: list[Change] | None = None,
) -> None:
    """Write one activity row for one change to a logical skill.

    `LLMSkill` has no `ModelActivityMixin`: a publish inserts a new row and archive uses
    `QuerySet.update()`, so the mixin would log each version as created and miss the archive.
    The skill service functions call this instead, once per change. Without an `item_id`, the
    skill's first live version supplies it.
    """
    item_id = item_id or skill_activity_item_id(team, skill_name)
    if item_id is None:
        return
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=user,
        was_impersonated=activity_storage.get_was_impersonated(),
        item_id=item_id,
        scope=SKILL_ACTIVITY_SCOPE,
        activity=activity,
        detail=Detail(name=skill_name, changes=changes),
    )


def skill_change(field: str, *, before: Any = None, after: Any = None) -> Change:
    return Change(type=SKILL_ACTIVITY_SCOPE, action="changed", field=field, before=before, after=after)


def version_changes(previous: LLMSkill, published: LLMSkill) -> list[Change]:
    """The changes between two versions of one skill, with the version note first."""
    changes = [skill_change("version", before=previous.version, after=published.version)]
    if published.version_description:
        changes.append(
            Change(
                type=SKILL_ACTIVITY_SCOPE,
                action="created",
                field="version_description",
                after=published.version_description,
            )
        )
    if previous.body != published.body:
        changes.append(skill_change("body"))
    for field in _PUBLISHED_FIELDS:
        before, after = getattr(previous, field), getattr(published, field)
        if before != after:
            changes.append(skill_change(field, before=before, after=after))
    files_change = _files_change(previous, published)
    if files_change is not None:
        changes.append(files_change)
    return changes


def _files_change(previous: LLMSkill, published: LLMSkill) -> Change | None:
    # Compare digests, not content: a skill can hold 200 files of up to 1 MB each.
    digests_by_skill: dict[Any, dict[str, str | None]] = {previous.pk: {}, published.pk: {}}
    for skill_id, path, digest in LLMSkillFile.objects.filter(skill_id__in=digests_by_skill).values_list(
        "skill_id", "path", "content_sha256"
    ):
        digests_by_skill[skill_id][path] = digest
    before, after = digests_by_skill[previous.pk], digests_by_skill[published.pk]
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    edited = sorted(path for path in before.keys() & after.keys() if before[path] != after[path])
    if not (added or removed or edited):
        return None
    return skill_change("files", after={"added": added, "removed": removed, "edited": edited})
