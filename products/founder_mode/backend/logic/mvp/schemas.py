"""Pydantic schemas for the MVP happy-path stage (stage 4).

PLACEHOLDER — the exact content shape is still in flux. The current schema captures a minimal
"smallest end-to-end happy path" brief: one-liner, 3-7 step user journey, must-haves, and
out-of-scope. We'll iterate on this once the FE for stage 4 lands.
"""

from pydantic import BaseModel, ConfigDict, Field

from products.founder_mode.backend.logic.envelope import StageStatus


class HappyPathStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(description="1-indexed step number in the user journey.")
    user_action: str = Field(description="What the user does at this step — concrete, observable.")
    system_response: str = Field(description="What the product does in response — concrete, observable.")
    success_signal: str = Field(
        description="How we know this step worked — what the user sees, what gets logged, what state changes."
    )


class MVPHappyPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    one_liner: str = Field(description="One sentence describing what the MVP does end-to-end. No marketing language.")
    core_flow: list[HappyPathStep] = Field(
        description="3-7 step happy-path user journey from first touch to value delivered."
    )
    must_haves: list[str] = Field(description="Features that must ship in v1 to make the happy path work.")
    deliberately_excluded: list[str] = Field(
        description="Features explicitly NOT in v1 — the anti-bloat list. Each entry is one feature with a one-line reason."
    )


class MVPEnvelope(BaseModel):
    """API-facing envelope for the `mvp` JSON column."""

    status: StageStatus | None = Field(default=None, description="Lifecycle state of the MVP generation run.")
    result: MVPHappyPath | None = Field(
        default=None, description="The MVP happy-path spec. Present once `status='completed'`."
    )
    started_at: str | None = Field(default=None, description="ISO timestamp when the run kicked off.")
    completed_at: str | None = Field(default=None, description="ISO timestamp when the run finished successfully.")
    failed_at: str | None = Field(default=None, description="ISO timestamp when the run failed.")
    trace_id: str | None = Field(default=None, description="Trace id linking to the underlying LLM calls.")
    error: str = Field(default="", description="Human-readable error message when `status='failed'`. Empty otherwise.")
