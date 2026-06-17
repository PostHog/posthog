from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class SynthesisStatus(str, Enum):
    SYNTHESIZED = "synthesized"  # markdown produced + persisted; deliver it
    SKIPPED_EMPTY = "skipped_empty"  # nothing to deliver — no observations matched, or the model returned empty
    SKIPPED_OVER_BUDGET = "skipped_over_budget"  # team over AI credit budget
    ABORTED_NO_CONSENT = "aborted_no_consent"  # org has not approved AI data processing
    ABORTED_NO_USER = "aborted_no_user"  # creator was deleted; can't attribute the LLM call


class SynthesizeGroupSummaryInputs(BaseModel, frozen=True):
    # The run already references its action (run.vision_action), so run_id is sufficient.
    run_id: UUID


class SynthesizeGroupSummaryResult(BaseModel, frozen=True):
    status: SynthesisStatus
    observation_count: int = 0


# --- engine (scheduling + per-action processing) ---


class ScheduleAllVisionActionsInputs(BaseModel, frozen=True):
    # Look-ahead so an action whose next_run_at falls within the next tick is picked up now.
    buffer_seconds: int = 120


class DueVisionAction(BaseModel, frozen=True):
    vision_action_id: UUID
    team_id: int
    scheduled_at: datetime | None = None


class ProcessVisionActionInputs(BaseModel, frozen=True):
    vision_action_id: UUID
    team_id: int
    scheduled_at: datetime | None = None


class CreateVisionActionRunInputs(BaseModel, frozen=True):
    vision_action_id: UUID
    team_id: int
    idempotency_key: str
    temporal_workflow_id: str
    scheduled_at: datetime | None = None


class UpdateVisionActionRunInputs(BaseModel, frozen=True):
    run_id: UUID
    status: str
    error: dict | None = None


class EmitActionReadyInputs(BaseModel, frozen=True):
    run_id: UUID
