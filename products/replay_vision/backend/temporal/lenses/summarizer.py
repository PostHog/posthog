"""Summarizer lens: produces a title and a text summary."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph",
    "long": "3-5 paragraphs",
}


class SummarizerOutput(BaseLensOutput, frozen=True):
    lens_type: Literal[LensType.SUMMARIZER] = LensType.SUMMARIZER
    title: str = Field(max_length=120, description="Short title for the session (~80 chars). Plain text, no quotes.")
    summary: str = Field(description="Body text whose length follows the lens's configured length.")


class SummarizerLens(BaseLens, frozen=True):
    lens_type: Literal[LensType.SUMMARIZER] = LensType.SUMMARIZER
    prompt_template: ClassVar[str] = "summarizer.jinja"
    length: SummaryLength = "medium"

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return SummarizerOutput

    def prompt_context(self) -> dict[str, Any]:
        return {"length_guidance": _LENGTH_GUIDANCE[self.length]}
