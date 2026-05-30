"""Summarizer scanner: produces a title and a text summary, optionally with facet embeddings."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import BaseScanner, BaseScannerOutput

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph",
    "long": "3-5 paragraphs",
}


class SummarizerLlmResponse(BaseScannerOutput, frozen=True):
    """LLM-facing schema (title + summary). Used when `emits_embeddings=False` to keep the schema lean."""

    title: str = Field(max_length=120, description="Short title for the session (~80 chars). Plain text, no quotes.")
    summary: str = Field(description="Body text whose length follows the scanner's configured length.")


class SummarizerWithFacetsLlmResponse(SummarizerLlmResponse, frozen=True):
    """Extended LLM-facing schema with embedding facets. Used when `emits_embeddings=True`."""

    intent: str = Field(
        description=(
            "One sentence describing what the user was trying to accomplish at the start of the session "
            "(their goal), regardless of whether they succeeded."
        ),
    )
    outcome: str = Field(
        description=(
            "One sentence describing the final state — where the user ended up and whether they accomplished "
            "their intent. Do not restate the summary."
        ),
    )
    friction_points: list[str] = Field(
        description=(
            "Named blockers, errors, or frustrations encountered, lowercase phrases "
            "(e.g. 'login failure', 'buffering during replay'). Empty list when friction-free."
        ),
    )
    keywords: list[str] = Field(
        description=(
            "5-15 distinctive lowercase keywords for free-text search. Favor concrete action verbs "
            "(clicked, abandoned, retried, submitted) and specific feature names. "
            "Avoid generic terms that apply to most sessions ('user', 'session', 'navigation'); "
            "avoid the team or product brand name."
        ),
    )

    @field_validator("keywords", "friction_points", mode="after")
    @classmethod
    def _lowercase(cls, value: list[str]) -> list[str]:
        # Lowercase so embedding similarity isn't fragmented by mixed casing.
        return [v.lower() for v in value]


class SummarizerOutput(SummarizerLlmResponse, frozen=True):
    """Persisted output: facet fields default to empty so flag-off summarizers round-trip cleanly."""

    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    intent: str = ""
    outcome: str = ""
    friction_points: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    def has_any_facet(self) -> bool:
        """True when the LLM filled at least one facet field; gates the embedding side-effect."""
        return bool(self.intent or self.outcome or self.friction_points or self.keywords)


class SummarizerScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    prompt_template: ClassVar[str] = "summarizer.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("summary",)
    output_cls: ClassVar[type[BaseScannerOutput]] = SummarizerOutput
    length: SummaryLength = "medium"
    emits_embeddings: bool = False

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return SummarizerWithFacetsLlmResponse if self.emits_embeddings else SummarizerLlmResponse

    def prompt_context(self) -> dict[str, Any]:
        return {
            "length_guidance": _LENGTH_GUIDANCE[self.length],
            "emits_embeddings": self.emits_embeddings,
        }
