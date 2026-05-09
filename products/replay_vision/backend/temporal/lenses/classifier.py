from typing import Any

from pydantic import Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import (
    BASE_CONFIDENCE_INSTRUCTION,
    BaseFinalOutput,
    BaseSegmentOutput,
    Lens,
)


class ClassifierSegmentOutput(BaseSegmentOutput):
    tags: list[str] = Field(description="Subset of the configured tags that apply to this segment.")
    reasoning: str = Field(description="Brief justification for the tag selection.")


class ClassifierOutput(BaseFinalOutput):
    tags: list[str] = Field(description="Tags that apply anywhere in the session.")
    reasoning: str = Field(description="Aggregated reasoning across segments.")


class ClassifierLens(Lens[ClassifierSegmentOutput, ClassifierOutput]):
    lens_type = LensType.CLASSIFIER
    SegmentOutput = ClassifierSegmentOutput
    FinalOutput = ClassifierOutput

    @classmethod
    def system_prompt(cls, lens_config: dict[str, Any]) -> str:
        user_prompt = lens_config["prompt"]
        tags: list[str] = lens_config["tags"]
        multi_label: bool = lens_config.get("multi_label", True)
        cardinality = "all that apply" if multi_label else "exactly one"
        return (
            "You are a session-replay classifier. Watch this session segment and pick "
            f"{cardinality} of the following tags.\n\n"
            f"Instructions: {user_prompt}\n\n"
            f"Allowed tags: {', '.join(tags)}\n\n"
            "Output JSON with `tags` (subset of the allowed list — never invent new ones), a brief "
            f"`reasoning`, and `confidence`. {BASE_CONFIDENCE_INSTRUCTION}"
        )

    @classmethod
    async def consolidate(
        cls,
        segment_outputs: list[ClassifierSegmentOutput],
        lens_config: dict[str, Any],
    ) -> ClassifierOutput:
        if not segment_outputs:
            return ClassifierOutput(tags=[], reasoning="(no segments analyzed)", confidence=0.0)
        # Union of tags across segments. Drop anything outside the configured allowlist as a safety net.
        allowed: set[str] = set(lens_config.get("tags", []))
        tags = sorted({t for s in segment_outputs for t in s.tags if not allowed or t in allowed})
        reasoning = "\n".join(f"[seg {i}] {s.reasoning}" for i, s in enumerate(segment_outputs))
        confidence = sum(s.confidence for s in segment_outputs) / len(segment_outputs)
        return ClassifierOutput(tags=tags, reasoning=reasoning, confidence=confidence)
