from django.db import IntegrityError, transaction
from django.db.models import F

from rest_framework.serializers import ValidationError as DRFValidationError

from posthog.models import Team, User

from ..models.community_skills import CommunitySkill, CommunitySkillVote
from ..models.skills import LLMSkill
from .skill_serializers import validate_allowed_tool, validate_skill_file_path, validate_skill_name_value
from .skill_services import MAX_SKILL_FILE_BYTES, create_skill

# Community skills must not land in the reserved Signals-scout namespace: on a Signals-enrolled team
# the coordinator auto-registers and executes every `signals-scout-*` skill with privileged scopes,
# so a community contributor could otherwise have attacker-controlled instructions auto-run against
# an installing team. Canonical scouts are seeded through a separate, authorized path, never install.
RESERVED_INSTALL_NAME_PREFIXES = ("signals-scout-",)


class CommunitySkillNotFoundError(Exception):
    pass


class CommunitySkillInvalidPayloadError(Exception):
    """The synced catalog entry can't be safely copied into a team — a traversal/reserved file path,
    oversized file content, a whitespace-bearing tool name, an empty body, or a reserved privileged
    namespace. Surfaced as a 400 rather than persisting a malformed team skill."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def get_community_skill_by_slug(slug: str) -> CommunitySkill | None:
    return CommunitySkill.objects.filter(slug=slug, deleted=False).first()


def _first_error_detail(err: DRFValidationError) -> str:
    detail = err.detail
    if isinstance(detail, list) and detail:
        return str(detail[0])
    return str(detail)


def _validate_installable_files(source: CommunitySkill) -> list[dict[str, str]]:
    """Re-run the same path/size guards as the regular skill create/import flows.

    create_skill only checks file count and exact-duplicate paths, so without this a catalog file
    shipping `../x`, a reserved name, control characters, or oversized content would be persisted
    into the team skill and later corrupt exports or marketplace clones.
    """
    validated: list[dict[str, str]] = []
    for f in source.files.all():
        try:
            path = validate_skill_file_path(f.path)
        except DRFValidationError as err:
            raise CommunitySkillInvalidPayloadError(
                f"Bundled file '{f.path}' is invalid: {_first_error_detail(err)}"
            ) from err
        if len(f.content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise CommunitySkillInvalidPayloadError(f"Bundled file '{path}' exceeds the size limit.")
        validated.append({"path": path, "content": f.content, "content_type": f.content_type})
    return validated


def install_community_skill(
    *,
    team: Team,
    user: User,
    slug: str,
    new_name: str | None = None,
) -> LLMSkill:
    """Copy a community skill into a team as a regular LLMSkill and bump its install counter.

    Raises CommunitySkillNotFoundError if the slug is unknown, LLMSkillDuplicateNameConflictError
    if the target name already exists in the team, and CommunitySkillInvalidPayloadError if the
    catalog entry can't be safely installed.
    """
    community_skill = get_community_skill_by_slug(slug)
    if community_skill is None:
        raise CommunitySkillNotFoundError()

    try:
        target_name = validate_skill_name_value(new_name or community_skill.slug)
    except DRFValidationError as err:
        raise CommunitySkillInvalidPayloadError(_first_error_detail(err)) from err

    if any(target_name.startswith(prefix) for prefix in RESERVED_INSTALL_NAME_PREFIXES):
        raise CommunitySkillInvalidPayloadError(
            "That name is reserved for PostHog-managed Signals scouts and can't be used for a community install."
        )

    for tool in community_skill.allowed_tools or []:
        try:
            validate_allowed_tool(tool)
        except DRFValidationError as err:
            raise CommunitySkillInvalidPayloadError(_first_error_detail(err)) from err

    with transaction.atomic():
        # Lock the catalog row so a concurrent sync can't replace the body/metadata after we read
        # them but before we copy the files — otherwise the install could be a hybrid of two
        # revisions. create_skill + the counter bump then commit together or not at all.
        locked = CommunitySkill.objects.select_for_update().get(pk=community_skill.pk)
        if not (locked.body or "").strip():
            raise CommunitySkillInvalidPayloadError("This community skill has no instructions and can't be installed.")
        files = _validate_installable_files(locked)

        installed = create_skill(
            team,
            user=user,
            name=target_name,
            description=locked.description,
            body=locked.body,
            license=locked.license,
            compatibility=locked.compatibility,
            allowed_tools=locked.allowed_tools,
            # Stamp provenance so an installed skill can be traced back to its community source.
            metadata={
                **(locked.metadata or {}),
                "community_skill_slug": locked.slug,
                "community_skill_id": str(locked.id),
            },
            files=files or None,
        )

        CommunitySkill.objects.filter(pk=locked.pk).update(install_count=F("install_count") + 1)
    return installed


def toggle_community_skill_vote(*, slug: str, user: User) -> tuple[int, bool]:
    """Add or remove the user's upvote. Returns (vote_count, has_voted) after the toggle."""
    community_skill = get_community_skill_by_slug(slug)
    if community_skill is None:
        raise CommunitySkillNotFoundError()

    with transaction.atomic():
        existing = CommunitySkillVote.objects.filter(skill=community_skill, user=user).first()
        if existing is not None:
            existing.delete()
            has_voted = False
        else:
            try:
                # Nested atomic → a SAVEPOINT: if a concurrent request inserted the vote first, the
                # IntegrityError rolls back only to here, leaving the outer transaction healthy so
                # the count() below still runs (a bare except would poison the whole transaction).
                with transaction.atomic():
                    CommunitySkillVote.objects.create(skill=community_skill, user=user)
                has_voted = True
            except IntegrityError:
                # Concurrent request created the vote first — converge on the "voted" state.
                has_voted = True
        vote_count = CommunitySkillVote.objects.filter(skill=community_skill).count()

    return vote_count, has_voted
