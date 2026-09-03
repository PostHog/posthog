"""Summarizer scanner: a single `summary` turn (title + body), embedded whole for free-text search."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    MissionStep,
    Segment,
    SignalFinding,
    confidence_field,
)
from products.replay_vision.backend.temporal.scanners.prompt_env import render_prompt

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph",
    "long": "3-5 paragraphs",
}


class SummarizerSummaryResponse(BaseModel, frozen=True):
    """First turn: the title + body summary. Field order is load-bearing — `confidence` last, after the content."""

    title: str = Field(
        max_length=120,
        description=(
            "Short title for the session (~80 chars). Plain text, no quotes. If the team's context specifies "
            "a naming convention or format for observations, the title must follow it exactly."
        ),
    )
    summary: str = Field(description="Body text whose length follows the scanner's configured length.")
    confidence: float = confidence_field()


class SummarizerOutput(BaseScannerOutput, frozen=True):
    """Persisted output: the summary turn's fields."""

    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    title: str = ""
    summary: str = ""
    summary_segments: list[Segment] = Field(default_factory=list)


def summary_embedding_text(output: SummarizerOutput) -> str:
    """The single document embedded for search: title and body together, so a query can match either."""
    return "\n\n".join(part for part in (output.title.strip(), output.summary.strip()) if part)


class SummarizerScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    citation_fields: ClassVar[tuple[str, ...]] = ("summary",)
    output_cls: ClassVar[type[BaseScannerOutput]] = SummarizerOutput
    length: SummaryLength = "medium"

    def core_steps(self) -> list[MissionStep]:
        summary_instruction = render_prompt(
            "summarizer_summary_step.jinja",
            user_prompt=self.prompt,
            length_guidance=_LENGTH_GUIDANCE[self.length],
        )
        return [
            MissionStep(name="summary", instruction=summary_instruction, response_model=SummarizerSummaryResponse),
        ]

    def assemble(self, step_outputs: dict[str, BaseModel]) -> tuple[BaseScannerOutput, list[SignalFinding]]:
        summary = step_outputs["summary"]
        return SummarizerOutput(**summary.model_dump()), self._extract_signals(step_outputs)
