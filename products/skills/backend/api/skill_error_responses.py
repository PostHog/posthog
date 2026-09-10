"""The error responses more than one skill endpoint answers with.

Every skill write funnels its service-layer errors through ``skill_write_error_response``, so a
given failure reads the same whichever endpoint hit it.
"""

from typing import Any

from rest_framework import status
from rest_framework.response import Response

from .skill_services import (
    LLMSkillDescriptionTooLongError,
    LLMSkillEditError,
    LLMSkillFileLimitError,
    LLMSkillNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
)


def skill_not_found_response(skill_name: str) -> Response:
    return Response(
        {"detail": f"Skill with name '{skill_name}' not found."},
        status=status.HTTP_404_NOT_FOUND,
    )


def version_conflict_response(current_version: int) -> Response:
    return Response(
        {
            "detail": "The skill changed since you opened it. Reload the latest version and try again.",
            "current_version": current_version,
        },
        status=status.HTTP_409_CONFLICT,
    )


def skill_write_error_response(err: Exception, skill_name: str) -> Response | None:
    """Render a service-layer write error. Returns None for an error with no shared rendering.

    A caller only reaches this for the errors it catches itself, so returning None means the caller
    caught something it has no response for and must re-raise.
    """
    if isinstance(err, LLMSkillNotFoundError):
        return skill_not_found_response(skill_name)
    if isinstance(err, LLMSkillVersionConflictError):
        return version_conflict_response(err.current_version)
    if isinstance(err, LLMSkillVersionLimitError):
        return Response(
            {
                "detail": (
                    f"Skill has reached the maximum of {err.max_version} versions. "
                    "Archive and recreate the skill to continue publishing."
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(err, LLMSkillFileLimitError):
        return Response(
            {"detail": f"Skill has reached the maximum of {err.max_count} files."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(err, LLMSkillDescriptionTooLongError):
        return Response(
            {
                "detail": (
                    f"Shorten the skill description to {err.max_length} characters before creating a new version."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(err, LLMSkillEditError):
        error_body: dict[str, Any] = {"detail": err.message}
        if err.edit_index is not None:
            error_body["edit_index"] = err.edit_index
        if err.file_path is not None:
            error_body["file_path"] = err.file_path
        return Response(error_body, status=status.HTTP_400_BAD_REQUEST)
    return None


def spec_problems_detail(lead: str, problems: list[str], next_step: str) -> str:
    # Clients such as the app toast show only `detail`, so the specific problems must live there too.
    sentences = ". ".join((problem[:1].upper() + problem[1:]).removesuffix(".") for problem in problems)
    return f"{lead} {sentences}. {next_step}"
