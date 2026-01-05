"""Pydantic schemas for structured survey summarization outputs."""

from typing import Literal

from pydantic import BaseModel, Field


class SurveyTheme(BaseModel):
    """A theme identified from survey responses."""

    theme: str = Field(description="Theme name (2-5 words)")
    description: str = Field(description="Brief description with 1-2 supporting quotes")
    frequency: Literal["common", "moderate", "rare"] = Field(description="How prevalent this theme is across responses")


class SurveySummaryResponse(BaseModel):
    """Structured response for survey summary."""

    overview: str = Field(description="1-2 sentence high-level summary of the responses")
    themes: list[SurveyTheme] = Field(
        description="Key themes identified (3-5 themes, ordered by frequency)",
        min_length=1,
        max_length=5,
    )
    key_insight: str = Field(description="Most actionable insight for the product team")
