"""The limits an uploaded skill zip must clear before it becomes a skill."""

from collections.abc import Callable, Sequence
from typing import Any

from rest_framework import serializers

from ..marketplace.packaging import SkillExport, SkillFileExport, validate_for_export
from .skill_serializers import (
    MAX_SKILL_FILE_BYTES,
    validate_allowed_tool,
    validate_skill_body_size,
    validate_skill_file_path,
    validate_skill_name_value,
)

# Generous ceiling for an uploaded skill zip — per-skill content (body, 200 files × 1 MB) is
# already bounded by create_skill, this just caps the upload before we read it into memory.
MAX_IMPORT_ZIP_BYTES = 10_000_000


def import_problems(skill_export: SkillExport) -> list[str]:
    """Every reason this zip cannot be imported, as sentences for the caller. Empty == importable.

    The import path calls create_skill directly, so it must re-apply the same size/shape limits the
    create/edit serializers enforce — otherwise a spec-valid zip could persist content (oversized
    body/files, whitespace-bearing tools) the rest of the system assumes is bounded.
    validate_for_export already covers the description (non-empty, <= spec limit).
    """
    return [
        *validate_for_export(skill_export),
        *_metadata_problems(skill_export),
        *_file_problems(skill_export.files),
    ]


def _metadata_problems(skill_export: SkillExport) -> list[str]:
    problems = [
        *_validation_problem("name", validate_skill_name_value, skill_export.name),
        *_validation_problem("body", validate_skill_body_size, skill_export.body),
    ]
    for tool in skill_export.allowed_tools:
        problems += _validation_problem(f"allowed-tools '{tool}'", validate_allowed_tool, tool)
    if len(skill_export.license) > 255:
        problems.append("license must be 255 characters or fewer")
    if len(skill_export.compatibility) > 500:
        problems.append("compatibility must be 500 characters or fewer")
    return problems


def _file_problems(files: Sequence[SkillFileExport]) -> list[str]:
    problems: list[str] = []
    seen_lower: set[str] = set()
    for skill_file in files:
        problems += _validation_problem(f"file '{skill_file.path}'", validate_skill_file_path, skill_file.path)
        if len(skill_file.content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            problems.append(f"file '{skill_file.path}': content must be {MAX_SKILL_FILE_BYTES} bytes or fewer")
        lowered = skill_file.path.lower()
        if lowered in seen_lower:
            problems.append(f"file '{skill_file.path}': collides with another file (case-insensitive)")
        seen_lower.add(lowered)
    return problems


def _validation_problem(label: str, validate: Callable[[Any], Any], value: Any) -> list[str]:
    try:
        validate(value)
    except serializers.ValidationError as err:
        return [f"{label}: {_first_error(err)}"]
    return []


def _first_error(err: serializers.ValidationError) -> str:
    detail = err.detail
    if isinstance(detail, list) and detail:
        return str(detail[0])
    return str(detail)
