from typing import Any

from pydantic import Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import (
    BASE_CONFIDENCE_INSTRUCTION,
    BaseFinalOutput,
    BaseSegmentOutput,
    Lens,
)


class MonitorSegmentOutput(BaseSegmentOutput):
    verdict: bool = Field(description="True if the condition was observed in this segment.")
    reasoning: str = Field(description="Brief justification for the verdict.")


class MonitorOutput(BaseFinalOutput):
    verdict: bool = Field(description="True if the condition was observed anywhere in the session.")
    reasoning: str = Field(description="Aggregated reasoning across segments.")


class MonitorLens(Lens[MonitorSegmentOutput, MonitorOutput]):
    lens_type = LensType.MONITOR
    SegmentOutput = MonitorSegmentOutput
    FinalOutput = MonitorOutput

    @classmethod
    def system_prompt(cls, lens_config: dict[str, Any]) -> str:
        user_prompt = lens_config["prompt"]
        return (
            "You are a session-replay monitor. Watch this session segment and decide whether the "
            "condition described below was observed.\n\n"
            f"Condition: {user_prompt}\n\n"
            "Output JSON with `verdict` (true if observed in this segment), a brief `reasoning`, "
            f"and `confidence`. {BASE_CONFIDENCE_INSTRUCTION}"
        )

    @classmethod
    async def consolidate(
        cls,
        segment_outputs: list[MonitorSegmentOutput],
        lens_config: dict[str, Any],
    ) -> MonitorOutput:
        if not segment_outputs:
            return MonitorOutput(verdict=False, reasoning="(no segments analyzed)", confidence=0.0)
        verdict = any(s.verdict for s in segment_outputs)
        reasoning = "\n".join(f"[seg {i}] {s.reasoning}" for i, s in enumerate(segment_outputs))
        # If verdict varies across segments, take the min — disagreement reduces confidence.
        # Otherwise average: consistent agreement = take the mean.
        verdicts_agree = len({s.verdict for s in segment_outputs}) == 1
        confidences = [s.confidence for s in segment_outputs]
        confidence = min(confidences) if not verdicts_agree else sum(confidences) / len(confidences)
        return MonitorOutput(verdict=verdict, reasoning=reasoning, confidence=confidence)
