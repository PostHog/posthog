"""Summarizer scanner: produces a title and a text summary."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import BaseScanner, BaseScannerOutput

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph",
    "long": "3-5 paragraphs",
}


class SummarizerLlmResponse(BaseScannerOutput, frozen=True):
    """LLM-facing schema: the model decides these fields; `scanner_type` is stamped by the workflow in `finalize`."""

    title: str = Field(max_length=120, description="Short title for the session (~80 chars). Plain text, no quotes.")
    summary: str = Field(description="Body text whose length follows the scanner's configured length.")


class SummarizerOutput(SummarizerLlmResponse, frozen=True):
    """Persisted output: adds the discriminator for the `AnyScannerOutput` union."""

    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER


class SummarizerScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    prompt: str
    prompt_template: ClassVar[str] = "summarizer.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("summary",)
    output_cls: ClassVar[type[BaseScannerOutput]] = SummarizerOutput
    length: SummaryLength = "medium"

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return SummarizerLlmResponse

    def prompt_context(self) -> dict[str, Any]:
        return {"length_guidance": _LENGTH_GUIDANCE[self.length]}
