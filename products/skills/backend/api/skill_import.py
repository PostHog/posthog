"""The limits an uploaded skill zip must clear before it becomes a skill."""

from collections.abc import Callable, Sequence
from typing import Any

from rest_framework import serializers

from ..marketplace.packaging import SkillExport, SkillFileExport
from .skill_serializers import (
    MAX_SKILL_FILE_BYTES,
    validate_allowed_tool,
    validate_new_skill_name_value,
    validate_skill_body_size,
)
from .skill_services import compute_spec_problems, skill_name_is_well_formed

# Generous ceiling for an uploaded skill zip — per-skill content (body, 200 files × 1 MB) is
# already bounded by create_skill, this just caps the upload before we read it into memory.
MAX_IMPORT_ZIP_BYTES = 10_000_000


def import_problems(skill_export: SkillExport) -> list[str]:
    """Every reason this zip cannot be imported, as sentences for the caller. Empty == importable.

    The import path calls create_skill directly, so it must re-apply the same size/shape limits the
    create/edit serializers enforce — otherwise a spec-valid zip could persist content (oversized
    body/files, whitespace-bearing tools) the rest of the system assumes is bounded.
    The shared spec rules cover the description, name shape, and bundled-file paths.
    """
    return [
        *_spec_problem_messages(skill_export),
        *_metadata_problems(skill_export),
        *_file_problems(skill_export.files),
    ]


def _spec_problem_messages(skill_export: SkillExport) -> list[str]:
    """Render the shared packaging problems in the flat format used by API responses."""
    return [
        f"file '{problem.file_path}': {problem.message}" if problem.file_path else problem.message
        for problem in compute_spec_problems(
            skill_export.name,
            skill_export.description,
            [skill_file.path for skill_file in skill_export.files],
        )
    ]


def _metadata_problems(skill_export: SkillExport) -> list[str]:
    problems: list[str] = []
    # The reserved-name and bundled-name rules are all this adds on top of the shape rules above,
    # so calling it for a malformed name would report that defect twice.
    if skill_name_is_well_formed(skill_export.name):
        problems += _validation_problem("name", validate_new_skill_name_value, skill_export.name)
    problems += _validation_problem("body", validate_skill_body_size, skill_export.body)
    for tool in skill_export.allowed_tools:
        problems += _validation_problem(f"allowed-tools '{tool}'", validate_allowed_tool, tool)
    if len(skill_export.license) > 255:
        problems.append("license must be 255 characters or fewer")
    if len(skill_export.compatibility) > 500:
        problems.append("compatibility must be 500 characters or fewer")
    return problems


def _file_problems(files: Sequence[SkillFileExport]) -> list[str]:
    problems: list[str] = []
    for skill_file in files:
        # create_skill inserts the files with bulk_create, which runs no model validation, so a
        # path the column cannot hold reaches Postgres as a DataError and fails the request.
        if len(skill_file.path) > 500:
            problems.append(f"file '{skill_file.path}': path must be 500 characters or fewer")
        if len(skill_file.content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            problems.append(f"file '{skill_file.path}': content must be {MAX_SKILL_FILE_BYTES} bytes or fewer")
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
