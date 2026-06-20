from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F

from rest_framework.serializers import ValidationError as DRFValidationError

from posthog.models import Team, User

from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_BLIND_SPOTS_SKILL_NAMES,
    CANONICAL_PERSPECTIVE_SKILL_NAMES,
    CANONICAL_VALIDATION_SKILL_NAMES,
)

from ..models.community_skills import CommunitySkill, CommunitySkillVote
from ..models.skills import LLMSkill
from .skill_serializers import validate_allowed_tool, validate_skill_file_path, validate_skill_name_value
from .skill_services import MAX_SKILL_FILE_BYTES, create_skill
from .skill_template_services import parse_template_variables, render_template_skill

# Community skills must not land in the reserved Signals-scout namespace: on a Signals-enrolled team
# the coordinator auto-registers and executes every `signals-scout-*` skill with privileged scopes,
# so a community contributor could otherwise have attacker-controlled instructions auto-run against
# an installing team. Canonical scouts are seeded through a separate, authorized path, never install.
RESERVED_INSTALL_NAME_PREFIXES = ("signals-scout-",)

# ReviewHog's canonical skills auto-enable by name on a team's first PR review and run their body with
# review scopes, so a community install must not land on one of those exact names — otherwise a
# contributor's instructions would auto-run in an installing user's reviews. Only the canonical names
# are reserved; custom `review-hog-*` skills stay installable because they require explicit enablement.
RESERVED_INSTALL_NAMES = frozenset(
    CANONICAL_PERSPECTIVE_SKILL_NAMES + CANONICAL_VALIDATION_SKILL_NAMES + CANONICAL_BLIND_SPOTS_SKILL_NAMES
)

# Provenance keys ReviewHog stamps on the rows it manages. Its prune keys on `seeded_by`, so if a
# catalog entry carried these they could make a user's freshly installed skill disappear on the next
# review sync — strip them before stamping community provenance, the way duplicate_skill drops seeded_by.
_INTERNAL_METADATA_KEYS = frozenset({"seeded_by", "canonical_hash", "source"})


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
    variables: dict[str, str] | None = None,
) -> LLMSkill:
    """Copy a community skill into a team as a regular LLMSkill and bump its install counter.

    When the community skill is a template (its metadata declares `variables`), the user-supplied
    `variables` are bound into the body and bundled files before the LLMSkill is created.

    Raises CommunitySkillNotFoundError if the slug is unknown, LLMSkillDuplicateNameConflictError
    if the target name already exists in the team, CommunitySkillInvalidPayloadError if the catalog
    entry can't be safely installed, and MissingTemplateVariableError /
    UnknownTemplatePlaceholderError on template render failures.
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

    if target_name in RESERVED_INSTALL_NAMES:
        raise CommunitySkillInvalidPayloadError(
            "That name is reserved for PostHog-managed review skills and can't be used for a community install."
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
        # A concurrent sync could have soft-deleted the row between the initial lookup and this lock;
        # a PK query still returns it, so recheck under the lock rather than installing a removed skill.
        if locked.deleted:
            raise CommunitySkillNotFoundError()
        if not (locked.body or "").strip():
            raise CommunitySkillInvalidPayloadError("This community skill has no instructions and can't be installed.")
        # A blank description passes the sync's length-only check but later makes the installed skill
        # fail export validation, so reject it here rather than persisting an un-exportable skill.
        if not (locked.description or "").strip():
            raise CommunitySkillInvalidPayloadError("This community skill has no description and can't be installed.")
        files = _validate_installable_files(locked)
        body = locked.body

        # Stamp provenance so an installed skill can be traced back to its community source, but
        # first drop any internal ReviewHog ownership keys the catalog entry might carry.
        metadata: dict[str, Any] = {
            **{k: v for k, v in (locked.metadata or {}).items() if k not in _INTERNAL_METADATA_KEYS},
            "community_skill_slug": locked.slug,
            "community_skill_id": str(locked.id),
        }

        template_variables = parse_template_variables(locked.metadata)
        if template_variables:
            rendered = render_template_skill(
                variables=template_variables,
                body=locked.body,
                files=files,
                supplied=variables,
            )
            body = rendered.body
            files = rendered.files
            # The instantiated skill is a concrete skill, not a template — drop the variable schema and
            # record what it was rendered from so a re-render stays deterministic.
            metadata.pop("variables", None)
            metadata["instantiated_from"] = f"{locked.slug}@{locked.source_sha}"
            metadata["variable_bindings"] = rendered.bindings

        installed = create_skill(
            team,
            user=user,
            name=target_name,
            description=locked.description,
            body=body,
            license=locked.license,
            compatibility=locked.compatibility,
            allowed_tools=locked.allowed_tools,
            metadata=metadata,
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
