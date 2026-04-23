from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from posthog.models import Team, User

from ..models.skills import LLMSkill, LLMSkillFile, annotate_llm_skill_version_history_metadata

MAX_SKILL_VERSION = 2000
MAX_SKILL_BODY_BYTES = 1_000_000


class LLMSkillNotFoundError(Exception):
    pass


@dataclass
class LLMSkillVersionConflictError(Exception):
    current_version: int


@dataclass
class LLMSkillVersionLimitError(Exception):
    max_version: int


@dataclass
class LLMSkillEditError(Exception):
    message: str
    edit_index: int


class LLMSkillDuplicateNameConflictError(Exception):
    pass


def apply_skill_body_edits(body: str, edits: list[dict[str, str]]) -> str:
    """Apply sequential find/replace edits to a skill body.

    Each edit's 'old' text must match exactly once in the current body.
    """
    text = body
    for i, edit in enumerate(edits):
        old = edit["old"]
        new = edit["new"]
        count = text.count(old)
        if count == 0:
            raise LLMSkillEditError(
                message="Text to replace was not found in the skill body.",
                edit_index=i,
            )
        if count > 1:
            raise LLMSkillEditError(
                message=f"Text to replace matches {count} times — provide more context to make it unique.",
                edit_index=i,
            )
        text = text.replace(old, new, 1)

    if len(text.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise LLMSkillEditError(
            message=f"Resulting skill body exceeds the {MAX_SKILL_BODY_BYTES} byte size limit.",
            edit_index=len(edits) - 1,
        )

    return text


def get_active_skill_queryset(team: Team) -> QuerySet[LLMSkill]:
    return annotate_llm_skill_version_history_metadata(
        LLMSkill.objects.filter(team=team, deleted=False).select_related("created_by")
    )


def get_latest_skills_queryset(team: Team) -> QuerySet[LLMSkill]:
    return get_active_skill_queryset(team).filter(is_latest=True)


def get_skill_by_name_from_db(
    team: Team,
    skill_name: str,
    version: int | None = None,
    version_id: str | None = None,
) -> LLMSkill | None:
    queryset = get_active_skill_queryset(team).filter(name=skill_name)

    if version_id is not None:
        queryset = queryset.filter(id=version_id)
        if version is not None:
            queryset = queryset.filter(version=version)
        return queryset.order_by("created_at", "id").first()

    if version is None:
        return queryset.filter(is_latest=True).order_by("-version", "-created_at", "-id").first()

    return queryset.filter(version=version).order_by("created_at", "id").first()


def resolve_versions_page(
    team: Team,
    skill_name: str,
    *,
    limit: int,
    offset: int | None = None,
    before_version: int | None = None,
) -> tuple[list[LLMSkill], bool]:
    queryset = (
        LLMSkill.objects.filter(team=team, name=skill_name, deleted=False)
        .select_related("created_by")
        .order_by("-version", "-created_at", "-id")
    )

    if before_version is not None:
        queryset = queryset.filter(version__lt=before_version)
    elif offset is not None:
        versions = list(queryset[offset : offset + limit + 1])
        has_more = len(versions) > limit
        return versions[:limit], has_more

    versions = list(queryset[: limit + 1])
    has_more = len(versions) > limit
    return versions[:limit], has_more


def _carry_forward(payload_value: Any, current_value: Any) -> Any:
    return payload_value if payload_value is not None else current_value


def publish_skill_version(
    team: Team,
    *,
    user: User,
    skill_name: str,
    body: str | None = None,
    edits: list[dict[str, str]] | None = None,
    description: str | None = None,
    license: str | None = None,
    compatibility: str | None = None,
    allowed_tools: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    files: list[dict[str, str]] | None = None,
    base_version: int,
) -> LLMSkill:
    with transaction.atomic():
        current_latest = (
            LLMSkill.objects.select_for_update()
            .filter(team=team, name=skill_name, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        if current_latest is None:
            raise LLMSkillNotFoundError()

        if base_version != current_latest.version:
            raise LLMSkillVersionConflictError(current_version=current_latest.version)
        if current_latest.version >= MAX_SKILL_VERSION:
            raise LLMSkillVersionLimitError(max_version=MAX_SKILL_VERSION)

        if edits is not None:
            resolved_body = apply_skill_body_edits(current_latest.body, edits)
        else:
            resolved_body = _carry_forward(body, current_latest.body)

        LLMSkill.objects.filter(pk=current_latest.pk).update(is_latest=False)
        published_skill = LLMSkill.objects.create(
            team=team,
            name=current_latest.name,
            description=_carry_forward(description, current_latest.description),
            body=resolved_body,
            license=_carry_forward(license, current_latest.license),
            compatibility=_carry_forward(compatibility, current_latest.compatibility),
            allowed_tools=_carry_forward(allowed_tools, current_latest.allowed_tools),
            metadata=_carry_forward(metadata, current_latest.metadata),
            version=current_latest.version + 1,
            is_latest=True,
            created_by=user,
        )

        if files is not None:
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(
                        skill=published_skill,
                        path=file_data["path"],
                        content=file_data["content"],
                        content_type=file_data.get("content_type", "text/plain"),
                    )
                    for file_data in files
                ]
            )
        else:
            _copy_files(current_latest, published_skill)

        refreshed = get_active_skill_queryset(team).filter(pk=published_skill.pk).first()
        return refreshed if refreshed is not None else published_skill


def _copy_files(source_skill: LLMSkill, target_skill: LLMSkill) -> None:
    source_files = list(LLMSkillFile.objects.filter(skill=source_skill))
    if source_files:
        LLMSkillFile.objects.bulk_create(
            [
                LLMSkillFile(
                    skill=target_skill,
                    path=f.path,
                    content=f.content,
                    content_type=f.content_type,
                )
                for f in source_files
            ]
        )


def duplicate_skill(
    team: Team,
    *,
    user: User,
    source_name: str,
    new_name: str,
) -> LLMSkill:
    with transaction.atomic():
        source_latest = (
            LLMSkill.objects.select_for_update()
            .filter(team=team, name=source_name, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        if source_latest is None:
            raise LLMSkillNotFoundError()

        if LLMSkill.objects.filter(team=team, name=new_name, deleted=False).exists():
            raise LLMSkillDuplicateNameConflictError()

        try:
            new_skill = LLMSkill.objects.create(
                team=team,
                name=new_name,
                description=source_latest.description,
                body=source_latest.body,
                license=source_latest.license,
                compatibility=source_latest.compatibility,
                allowed_tools=source_latest.allowed_tools,
                metadata=source_latest.metadata,
                version=1,
                is_latest=True,
                created_by=user,
            )
        except IntegrityError as err:
            if "unique_llm_skill_latest_per_team" in str(err) or "unique_llm_skill_version_per_team" in str(err):
                raise LLMSkillDuplicateNameConflictError() from err
            raise

        _copy_files(source_latest, new_skill)

    refreshed = get_active_skill_queryset(team).filter(pk=new_skill.pk).first()
    return refreshed if refreshed is not None else new_skill


def archive_skill(team: Team, skill_name: str) -> list[int]:
    with transaction.atomic():
        skill_versions = list(
            LLMSkill.objects.select_for_update()
            .filter(team=team, name=skill_name, deleted=False)
            .order_by("version", "created_at", "id")
            .values_list("version", flat=True)
        )
        if not skill_versions:
            raise LLMSkillNotFoundError()
        LLMSkill.objects.filter(team=team, name=skill_name, deleted=False).update(
            deleted=True,
            is_latest=False,
        )
    return skill_versions
