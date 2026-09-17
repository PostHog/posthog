import dataclasses
from datetime import datetime
from enum import Enum
from typing import Any

import orjson

from products.wizard.backend.facade.contracts import WizardSessionDTO, WizardSessionUserDTO, WizardTaskDTO
from products.wizard.backend.facade.enums import WizardSessionRunPhase, WizardSessionTaskStatus
from products.wizard.backend.logic.sessions.staleness import is_stale
from products.wizard.backend.models import WizardSession


def serialize_session_dto(dto: WizardSessionDTO) -> bytes:
    return orjson.dumps(dto, default=_json_default)


def to_session_dto(instance: WizardSession) -> WizardSessionDTO:
    run_phase = WizardSessionRunPhase(instance.run_phase)
    created_by = instance.created_by
    return WizardSessionDTO(
        session_id=instance.session_id,
        team_id=instance.team_id,
        workflow_id=instance.workflow_id,
        skill_id=instance.skill_id,
        started_at=instance.started_at,
        run_phase=run_phase,
        is_stale=is_stale(run_phase, instance.updated_at),
        tasks=tuple(
            WizardTaskDTO(id=task["id"], title=task["title"], status=WizardSessionTaskStatus(task["status"]))
            for task in (instance.tasks or [])
        ),
        event_plan=instance.event_plan,
        error=instance.error,
        pending_input=instance.pending_input,
        handoff_text=instance.handoff_text,
        created_by=(
            WizardSessionUserDTO(id=created_by.id, first_name=created_by.first_name, email=created_by.email)
            if created_by is not None
            else None
        ),
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
