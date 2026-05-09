from typing import Any

from pydantic import Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import (
    BASE_CONFIDENCE_INSTRUCTION,
    BaseFinalOutput,
    BaseSegmentOutput,
    Lens,
)


class ScorerSegmentOutput(BaseSegmentOutput):
    score: float = Field(description="Numeric score for this segment, within the configured scale.")
    reasoning: str = Field(description="Brief justification for the score.")


class ScorerOutput(BaseFinalOutput):
    score: float = Field(description="Aggregate score across the session.")
    reasoning: str = Field(description="Aggregated reasoning across segments.")
    label: str | None = Field(default=None, description="Echo of `lens_config.scale.label` if set.")


class ScorerLens(Lens[ScorerSegmentOutput, ScorerOutput]):
    lens_type = LensType.SCORER
    SegmentOutput = ScorerSegmentOutput
    FinalOutput = ScorerOutput

    @classmethod
    def system_prompt(cls, lens_config: dict[str, Any]) -> str:
        user_prompt = lens_config["prompt"]
        scale = lens_config["scale"]
        scale_min = scale["min"]
        scale_max = scale["max"]
        label_clause = f" Label: {scale['label']}." if scale.get("label") else ""
        return (
            f"You are a session-replay scorer.{label_clause} Watch this session segment and produce a "
            f"numeric score between {scale_min} and {scale_max}.\n\n"
            f"Instructions: {user_prompt}\n\n"
            "Output JSON with `score` (in range), a brief `reasoning`, and `confidence`. "
            f"{BASE_CONFIDENCE_INSTRUCTION}"
        )

    @classmethod
    async def consolidate(
        cls,
        segment_outputs: list[ScorerSegmentOutput],
        lens_config: dict[str, Any],
    ) -> ScorerOutput:
        label = lens_config.get("scale", {}).get("label")
        if not segment_outputs:
            return ScorerOutput(score=0.0, reasoning="(no segments analyzed)", confidence=0.0, label=label)
        # Simple mean across segments. Phase 2 may switch to duration-weighted using segment length.
        score = sum(s.score for s in segment_outputs) / len(segment_outputs)
        reasoning = "\n".join(f"[seg {i}] {s.reasoning}" for i, s in enumerate(segment_outputs))
        confidence = sum(s.confidence for s in segment_outputs) / len(segment_outputs)
        return ScorerOutput(score=score, reasoning=reasoning, confidence=confidence, label=label)
