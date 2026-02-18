"""
Pydantic schema for structured LLM evaluation summary outputs.
"""

from pydantic import BaseModel, ConfigDict, Field


class EvaluationPattern(BaseModel):
    """A pattern identified across evaluation results."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Short title for the pattern (3-5 words)")
    description: str = Field(description="Detailed description of the pattern")
    frequency: str = Field(description="How common this pattern is: 'common', 'occasional', or 'rare'")
    example_reasoning: str = Field(
        description="An example reasoning from the evaluated runs that demonstrates this pattern"
    )
    example_generation_ids: list[str] = Field(description="List of 1-5 generation IDs that exemplify this pattern")


class EvaluationSummaryStatistics(BaseModel):
    """Statistics about the analyzed evaluation runs."""

    model_config = ConfigDict(extra="forbid")

    total_analyzed: int = Field(description="Total number of evaluation runs analyzed")
    pass_count: int = Field(description="Number of passing evaluations")
    fail_count: int = Field(description="Number of failing evaluations")
    na_count: int = Field(description="Number of N/A (not applicable) evaluations")


class EvaluationSummaryResponse(BaseModel):
    """Structured response from LLM evaluation summarization."""

    model_config = ConfigDict(extra="forbid")

    overall_assessment: str
    pass_patterns: list[EvaluationPattern]
    fail_patterns: list[EvaluationPattern]
    na_patterns: list[EvaluationPattern]
    recommendations: list[str]
    statistics: EvaluationSummaryStatistics
