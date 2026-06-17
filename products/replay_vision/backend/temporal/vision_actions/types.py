from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class SynthesisStatus(str, Enum):
    SYNTHESIZED = "synthesized"  # markdown produced + persisted; deliver it
    SKIPPED_EMPTY = "skipped_empty"  # no observations matched the window; nothing to deliver
    SKIPPED_OVER_BUDGET = "skipped_over_budget"  # team over AI credit budget
    ABORTED_NO_CONSENT = "aborted_no_consent"  # org has not approved AI data processing
    ABORTED_NO_USER = "aborted_no_user"  # creator was deleted; can't attribute the LLM call


class SynthesizeActionInputs(BaseModel, frozen=True):
    vision_action_id: UUID
    run_id: UUID


class SynthesizeActionResult(BaseModel, frozen=True):
    status: SynthesisStatus
    observation_count: int = 0
