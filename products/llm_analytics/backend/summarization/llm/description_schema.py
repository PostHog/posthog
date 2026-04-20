"""
Pydantic schema for structured LLM evaluation description generation outputs.
"""

from pydantic import BaseModel, ConfigDict, Field


class EvaluationDescriptionResponse(BaseModel):
    """Structured response from LLM evaluation description generation."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        description="A concise, 1-3 sentence description of what the evaluation checks for, in plain English.",
    )
