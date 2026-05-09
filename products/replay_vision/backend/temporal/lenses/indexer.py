from typing import Any

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


class IndexerSegmentOutput(BaseSegmentOutput):
    summary: str = Field(description="Single-sentence summary of this segment.")
    user_type: str = Field(description="Type of user observed in this segment.")
    outcome: str = Field(description="What the user achieved or attempted in this segment.")
    keywords: list[str] = Field(description="Keywords characterizing this segment.")


class IndexerOutput(BaseFinalOutput):
    summary: str = Field(description="Single-sentence summary of the whole session.")
    user_type: str = Field(description="Type of user observed across the session.")
    outcome: str = Field(description="What the user achieved or attempted across the session.")
    keywords: list[str] = Field(description="Aggregate keywords for the session.")


class IndexerLens(Lens[IndexerSegmentOutput, IndexerOutput]):
    lens_type = LensType.INDEXER
    SegmentOutput = IndexerSegmentOutput
    FinalOutput = IndexerOutput

    @classmethod
    def system_prompt(cls, lens_config: dict[str, Any]) -> str:
        user_prompt = lens_config.get("prompt", "Index this session for free-text similarity search.")
        return (
            "You are a session-replay indexer. Watch this session segment and produce four facets "
            "for downstream embedding / search.\n\n"
            f"Instructions: {user_prompt}\n\n"
            "Output JSON with `summary` (1 sentence), `user_type` (1 sentence), `outcome` "
            "(1 sentence), `keywords` (5-15 single words / short phrases), and `confidence`. "
            f"{BASE_CONFIDENCE_INSTRUCTION}"
        )

    @classmethod
    async def consolidate(
        cls,
        segment_outputs: list[IndexerSegmentOutput],
        lens_config: dict[str, Any],
    ) -> IndexerOutput:
        if not segment_outputs:
            return IndexerOutput(
                summary="(no segments analyzed)",
                user_type="unknown",
                outcome="unknown",
                keywords=[],
                confidence=0.0,
            )
        per_segment = "\n".join(
            f"[seg {i}] summary: {s.summary}\nuser_type: {s.user_type}\noutcome: {s.outcome}\n"
            f"keywords: {', '.join(s.keywords)}\nconfidence: {s.confidence:.2f}"
            for i, s in enumerate(segment_outputs)
        )
        consolidate_prompt = (
            "Merge these per-segment session indexes into one session-level index. Each facet "
            "should describe the WHOLE session, not just one segment. Keywords are deduped and "
            "sorted by salience.\n\n"
            f"Segments:\n{per_segment}\n\n"
            "Output JSON with `summary`, `user_type`, `outcome`, `keywords`, and `confidence`. "
            f"{BASE_CONFIDENCE_INSTRUCTION}"
        )
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        response = await client.models.generate_content(
            model=lens_config.get("consolidate_model", "gemini-3-flash"),
            contents=consolidate_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=IndexerOutput,
            ),
        )
        return IndexerOutput.model_validate_json((response.text or "").strip())
