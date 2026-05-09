from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_lens import LensType

BASE_CONFIDENCE_INSTRUCTION = (
    "Set `confidence` to your self-assessed certainty in this output, between 0.0 (pure guess) "
    "and 1.0 (certain). Calibrate honestly — high-confidence wrong answers are worse than "
    "low-confidence right ones."
)


class BaseSegmentOutput(BaseModel):
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-reported model confidence in this segment's output (0=guess, 1=certain).",
    )


class BaseFinalOutput(BaseModel):
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Aggregate confidence in the final lens output (0=guess, 1=certain).",
    )


SegmentOutputT = TypeVar("SegmentOutputT", bound=BaseSegmentOutput)
FinalOutputT = TypeVar("FinalOutputT", bound=BaseFinalOutput)


class Lens(ABC, Generic[SegmentOutputT, FinalOutputT]):
    """Per-lens-type encapsulation of prompt, schemas, and consolidate logic.

    Subclasses must set `lens_type`, `SegmentOutput`, `FinalOutput` as ClassVars and
    implement `system_prompt` + `consolidate`.
    """

    lens_type: ClassVar[LensType]
    SegmentOutput: ClassVar[type[BaseSegmentOutput]]
    FinalOutput: ClassVar[type[BaseFinalOutput]]

    @classmethod
    @abstractmethod
    def system_prompt(cls, lens_config: dict[str, Any]) -> str:
        """Build the per-segment Gemini prompt from the lens's user-configured prompt + type-specific instructions."""

    @classmethod
    @abstractmethod
    async def consolidate(
        cls,
        segment_outputs: list[SegmentOutputT],
        lens_config: dict[str, Any],
    ) -> FinalOutputT:
        """Merge per-segment outputs into one final output.

        Pure-Python lenses (monitor/classifier/scorer) implement this synchronously inside an async wrapper.
        LLM-driven lenses (summarizer/indexer) call Gemini here.
        """
