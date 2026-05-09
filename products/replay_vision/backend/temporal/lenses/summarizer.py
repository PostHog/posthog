from typing import Any, Literal

from django.conf import settings

from google.genai import types
from posthoganalytics.ai.gemini import genai
from pydantic import Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import (
    BASE_CONFIDENCE_INSTRUCTION,
    BaseFinalOutput,
    BaseSegmentOutput,
    Lens,
)

LengthOption = Literal["short", "medium", "long"]
LENGTH_GUIDANCE: dict[str, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph (3-5 sentences)",
    "long": "3-5 short paragraphs",
}


class SummarizerSegmentOutput(BaseSegmentOutput):
    title: str = Field(description="Title for this segment (~80 chars max).")
    summary: str = Field(description="Plain-text summary of this segment.")


class SummarizerOutput(BaseFinalOutput):
    title: str = Field(description="Title for the whole session (~80 chars max).")
    summary: str = Field(description="Plain-text summary of the whole session, length per lens config.")


def _length(lens_config: dict[str, Any]) -> LengthOption:
    return lens_config.get("length", "medium")


class SummarizerLens(Lens[SummarizerSegmentOutput, SummarizerOutput]):
    lens_type = LensType.SUMMARIZER
    SegmentOutput = SummarizerSegmentOutput
    FinalOutput = SummarizerOutput

    @classmethod
    def system_prompt(cls, lens_config: dict[str, Any]) -> str:
        user_prompt = lens_config["prompt"]
        return (
            "You are a session-replay summarizer. Watch this session segment and produce a short "
            "title plus a 1-2 sentence summary.\n\n"
            f"Instructions: {user_prompt}\n\n"
            "Output JSON with `title` (~80 chars), `summary` (1-2 sentences for this segment), and "
            f"`confidence`. {BASE_CONFIDENCE_INSTRUCTION}"
        )

    @classmethod
    async def consolidate(
        cls,
        segment_outputs: list[SummarizerSegmentOutput],
        lens_config: dict[str, Any],
    ) -> SummarizerOutput:
        if not segment_outputs:
            return SummarizerOutput(title="(empty)", summary="(no segments analyzed)", confidence=0.0)
        length = _length(lens_config)
        body_guidance = LENGTH_GUIDANCE[length]
        per_segment = "\n".join(
            f"[seg {i}] title: {s.title}\nsummary: {s.summary}\nconfidence: {s.confidence:.2f}"
            for i, s in enumerate(segment_outputs)
        )
        consolidate_prompt = (
            "Merge these per-segment session summaries into a single session-level summary. Produce "
            f"a title (~80 chars) and a `{length}` body ({body_guidance}). Stay grounded in the "
            "input — do not invent moments not described.\n\n"
            f"Segments:\n{per_segment}\n\n"
            f"Output JSON with `title`, `summary`, and `confidence`. {BASE_CONFIDENCE_INSTRUCTION}"
        )
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        response = await client.models.generate_content(
            model=lens_config.get("consolidate_model", "gemini-3-flash"),
            contents=consolidate_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SummarizerOutput,
            ),
        )
        return SummarizerOutput.model_validate_json((response.text or "").strip())
