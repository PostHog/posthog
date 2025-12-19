"""
Pydantic schema for structured LLM summarization outputs.
"""

from pydantic import BaseModel, ConfigDict, Field


class SummaryBullet(BaseModel):
    """A single bullet point in the summary."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The bullet point text")
    line_refs: str = Field(
        description="Single line reference like 'L45' pointing to the most relevant line for this bullet"
    )


class InterestingNote(BaseModel):
    """A single interesting note."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The note text")
    line_refs: str = Field(
        description="Single line reference like 'L45' pointing to the most relevant line, or empty string if no specific line"
    )


class SummarizationResponse(BaseModel):
    """Structured response from LLM summarization."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        description="A concise, descriptive title (no longer than 10 words) summarizing the main purpose or outcome of this trace/event"
    )
    flow_diagram: str = Field(
        description="ASCII/text-based flow diagram showing the main steps in an easy, human-readable way. Use arrows (↓, →), branches (├─→, └─→), and symbols (✓, ✗)."
    )
    summary_bullets: list[SummaryBullet] = Field(description="3-10 summary bullet points with line references")
    interesting_notes: list[InterestingNote] = Field(
        description="Interesting notes (detailed mode). Use empty array for minimal mode."
    )
