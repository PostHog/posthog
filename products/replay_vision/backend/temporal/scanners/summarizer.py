"""Summarizer scanner: one core turn producing a title + body, embedded whole for free-text search."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    EmbeddingDocument,
    Segment,
    confidence_field,
    notability_field,
    notability_reason_field,
)

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph",
    "long": "3-5 paragraphs",
}


class SummarizerSummaryResponse(BaseModel, frozen=True):
    """The core turn: title + body summary. Field order is load-bearing — `confidence` last, after the content."""

    title: str = Field(
        max_length=120,
        description=(
            "Short title for the session (~80 chars). Plain text, no quotes. If the team's context specifies "
            "a naming convention or format for observations, the title must follow it exactly."
        ),
    )
    summary: str = Field(description="Body text whose length follows the scanner's configured length.")
    notability_reason: str | None = notability_reason_field()
    notability: float | None = notability_field()
    confidence: float = confidence_field()


class SummarizerOutput(BaseScannerOutput, frozen=True):
    """Persisted output: the summary turn's fields."""

    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    title: str = ""
    summary: str = ""
    summary_segments: list[Segment] = Field(default_factory=list)

    def embedding_document(self) -> EmbeddingDocument | None:
        text = summary_embedding_text(self)
        return EmbeddingDocument(rendering="summary", text=text) if text else None


def summary_embedding_text(output: SummarizerOutput) -> str:
    """The single document embedded for search: title and body together, so a query can match either."""
    return "\n\n".join(part for part in (output.title.strip(), output.summary.strip()) if part)


class SummarizerScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    core_step_template: ClassVar[str] = "summarizer_summary_step.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("summary",)
    output_cls: ClassVar[type[BaseScannerOutput]] = SummarizerOutput
    length: SummaryLength = "medium"

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return SummarizerSummaryResponse

    def prompt_context(self) -> dict[str, Any]:
        return {"length_guidance": _LENGTH_GUIDANCE[self.length]}
