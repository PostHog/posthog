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
    # The run already references its action (run.vision_action); team_id scopes the fail-closed read.
    run_id: UUID
    team_id: int


class SynthesizeGroupSummaryResult(BaseModel, frozen=True):
    status: SynthesisStatus
    observation_count: int = 0


# --- engine (per-scanner eligibility + per-action processing) ---


class EvaluateDueVisionActionsInputs(BaseModel, frozen=True):
    # Scoped to one scanner (the sweep already knows scanner + team) → no cross-team scan.
    scanner_id: UUID
    team_id: int


class DueVisionAction(BaseModel, frozen=True):
    vision_action_id: UUID
    team_id: int
    # The next_run_at that fired this action, captured before the claim advanced it.
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


class ValidateVisionActionInputs(BaseModel, frozen=True):
    vision_action_id: UUID
    team_id: int


class UpdateVisionActionRunInputs(BaseModel, frozen=True):
    run_id: UUID
    team_id: int
    status: str
    error: dict | None = None


class EmitActionReadyInputs(BaseModel, frozen=True):
    run_id: UUID
    team_id: int
