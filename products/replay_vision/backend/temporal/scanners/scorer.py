"""Scorer scanner: produces a numeric score on a configured scale."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, create_model, model_validator

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    Segment,
    confidence_field,
)


class ScoreScale(BaseModel, frozen=True):
    min: float
    max: float
    label: str | None = None

    @model_validator(mode="after")
    def _min_lt_max(self) -> "ScoreScale":
        if self.min >= self.max:
            raise ValueError(f"scale.min ({self.min}) must be less than scale.max ({self.max})")
        return self


class ScorerOutput(BaseScannerOutput, frozen=True):
    scanner_type: Literal[ScannerType.SCORER] = ScannerType.SCORER
    score: float = Field(description="Numeric score on the configured scale.")
    reasoning: str = Field(description="One paragraph grounding the score in concrete moments.")
    reasoning_segments: list[Segment] = Field(default_factory=list)
    label: str | None = Field(
        default=None, description="Echoes `scanner_config.scale.label`; workflow-stamped, not model-generated."
    )


class ScorerScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.SCORER] = ScannerType.SCORER
    core_step_template: ClassVar[str] = "scorer_step.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("reasoning",)
    output_cls: ClassVar[type[BaseScannerOutput]] = ScorerOutput
    scale: ScoreScale

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        # Dynamic per instance: range + scale-label description steer Gemini at the schema level.
        score_description = f"Score on the '{self.scale.label}' scale" if self.scale.label else "Numeric score"
        # Field order is load-bearing: reasoning first (reason before scoring), confidence last.
        return create_model(
            "ScorerLlmResponse",
            reasoning=(str, Field(description="One paragraph grounding the score in concrete moments.")),
            score=(float, Field(ge=self.scale.min, le=self.scale.max, description=score_description)),
            confidence=(float, confidence_field()),
        )

    def prompt_context(self) -> dict[str, Any]:
        return {
            "scale_min": self.scale.min,
            "scale_max": self.scale.max,
            "scale_label": self.scale.label,
        }

    def finalize(self, llm_response: BaseModel) -> BaseScannerOutput:
        # Base builds the ScorerOutput from the response; only `label` is workflow-stamped, not model-generated.
        return super().finalize(llm_response).model_copy(update={"label": self.scale.label})

    def validate_semantics(self, output: BaseScannerOutput) -> str | None:
        if not isinstance(output, ScorerOutput):
            return f"Expected ScorerOutput, got {type(output).__name__}"
        if not (self.scale.min <= output.score <= self.scale.max):
            return f"Score {output.score} is outside the configured scale [{self.scale.min}, {self.scale.max}]"
        return None
