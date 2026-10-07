from __future__ import annotations

from uuid import UUID

from pydantic import JsonValue, ValidationError

from products.signals.backend.facade.rubrics import ScoutRubricNotFound, get_scout_rubric

type RubricDocument = dict[str, JsonValue]


class ScoutRubricReadError(ValueError):
    pass


class SavedScoutRubricReader:
    def __init__(self, *, team_id: int) -> None:
        self.team_id = team_id

    def read(self, *, config_id: UUID, skill_name: str) -> RubricDocument:
        try:
            document = get_scout_rubric(self.team_id, str(config_id))
        except ScoutRubricNotFound:
            raise ScoutRubricReadError(
                "The saved rubric was not found. Open this scout's rubric and save it first."
            ) from None
        except ValidationError:
            raise ScoutRubricReadError(
                "The saved rubric is invalid. Open this scout's rubric and save it again."
            ) from None
        if document.config_id != config_id or document.skill_name != skill_name:
            raise ScoutRubricReadError("The saved rubric does not belong to this scout.")
        state = document.state
        if state.revision <= 0:
            raise ScoutRubricReadError("Review and save this scout's rubric before scoring a comparison.")
        reference = state.reference_context
        if reference is None or state.reference_generation_id is None:
            raise ScoutRubricReadError(
                "This rubric has no saved reference instructions. Generate suggestions, review them, and save the rubric before scoring."
            )
        if reference.skill_name != skill_name:
            raise ScoutRubricReadError("The saved reference instructions do not belong to this scout.")
        if (
            reference.instructions_truncated
            or reference.reference_files_truncated
            or reference.reference_limits.omitted_files
            or reference.reference_limits.truncated_files
        ):
            raise ScoutRubricReadError(
                "The saved rubric's reference instructions are incomplete. Generate suggestions again, review and use the new reference, then save. You can keep your existing criteria."
            )
        return {
            "config_id": str(document.config_id),
            "skill_name": document.skill_name,
            **state.model_dump(mode="json"),
        }
