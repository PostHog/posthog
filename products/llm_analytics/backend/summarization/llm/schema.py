"""
Pydantic schema for structured LLM summarization outputs.
"""

from pydantic import BaseModel, ConfigDict, Field


class SummaryBullet(BaseModel):
    """A single bullet point in the summary."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The bullet point text")
    line_refs: str = Field(
        description="Single most relevant line reference like 'L45'. Do not use ranges or multiple references."
    )


class InterestingNote(BaseModel):
    """A single interesting note."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The note text")
    line_refs: str = Field(
        description="Single most relevant line reference like 'L45'. Use empty string if no line refs. Do not use ranges or multiple references."
    )


class SummarizationResponse(BaseModel):
    """Structured response from LLM summarization."""

    model_config = ConfigDict(extra="forbid")

    flow_diagram: str = Field(
        description="ASCII/text-based flow diagram showing the main steps in an easy, human-readable way. Use arrows (↓, →), branches (├─→, └─→), and symbols (✓, ✗)."
    )
    summary_bullets: list[SummaryBullet] = Field(description="3-10 summary bullet points with line references")
    interesting_notes: list[InterestingNote] = Field(
        description="Interesting notes (detailed mode). Use empty array for minimal mode."
    )
