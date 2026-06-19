"""Summarizer scanner: a `summary` turn (title + body) then a `facets` turn (embedding fields for free-text search)."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    MissionStep,
    Segment,
    SignalFinding,
    extract_signals,
)
from products.replay_vision.backend.temporal.scanners.prompt_env import render_prompt

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph",
    "long": "3-5 paragraphs",
}


class SummarizerSummaryResponse(BaseScannerOutput, frozen=True):
    """First turn: the title + body summary (and the shared `confidence`)."""

    title: str = Field(max_length=120, description="Short title for the session (~80 chars). Plain text, no quotes.")
    summary: str = Field(description="Body text whose length follows the scanner's configured length.")


class SummarizerFacetsResponse(BaseModel, frozen=True):
    """Second turn: facet fields that get embedded for downstream free-text search."""

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


class SummarizerOutput(BaseScannerOutput, frozen=True):
    """Persisted output: the summary turn's fields plus the (optional) facet turn's fields."""

    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    title: str = ""
    summary: str = ""
    summary_segments: list[Segment] = Field(default_factory=list)
    intent: str = ""
    outcome: str = ""
    friction_points: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    def has_any_facet(self) -> bool:
        """True when the facet turn filled at least one field; gates the embedding side-effect."""
        return bool(self.intent or self.outcome or self.friction_points or self.keywords)


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
        facets_instruction = render_prompt("summarizer_facets_step.jinja")
        return [
            MissionStep(name="summary", instruction=summary_instruction, response_model=SummarizerSummaryResponse),
            # Facets are nice-to-have: a failed facet turn must not cost us the summary it follows.
            MissionStep(
                name="facets",
                instruction=facets_instruction,
                response_model=SummarizerFacetsResponse,
                required=False,
            ),
        ]

    def assemble(self, step_outputs: dict[str, BaseModel]) -> tuple[BaseScannerOutput, list[SignalFinding]]:
        summary = step_outputs["summary"]
        facets = step_outputs.get("facets")
        fields: dict[str, Any] = {
            "confidence": summary.confidence,  # type: ignore[attr-defined]
            "title": summary.title,  # type: ignore[attr-defined]
            "summary": summary.summary,  # type: ignore[attr-defined]
        }
        if facets is not None:
            fields.update(facets.model_dump())
        return SummarizerOutput(**fields), extract_signals(step_outputs)
