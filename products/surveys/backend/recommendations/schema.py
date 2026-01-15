from typing import Literal

from pydantic import BaseModel, Field


class SurveyRecommendationOutput(BaseModel):
    source_type: Literal["insight", "experiment", "feature_flag"] = Field(
        description="The type of source object this recommendation is based on"
    )
    source_id: str = Field(
        description="The identifier: insight short_id, experiment ID (as string), or feature flag ID (as string)"
    )
    recommendation_type: Literal[
        "low_conversion_funnel", "declining_feature", "experiment_feedback", "feature_flag_feedback"
    ] = Field(description="The category of recommendation")
    title: str = Field(description="Short, descriptive title (e.g., 'Low conversion in Signup Funnel')")
    reason: str = Field(description="Why this survey is valuable (1-2 sentences)")
    suggested_question: str = Field(description="The main question the survey should ask users")
    score: int = Field(description="Priority score from 0-100 (higher = more important)", ge=0, le=100)
    trigger_event: str | None = Field(
        default=None,
        description="For funnels: the event name where users drop off (triggers the survey)",
    )
    cancel_event: str | None = Field(
        default=None,
        description="For funnels: the event name that cancels the survey if user completes it",
    )
    target_variant: str | None = Field(
        default=None,
        description="For multivariate flags/experiments: the variant key to target (e.g., 'control', 'treatment'). If null, targets all variants.",
    )


class RecommendationsResponse(BaseModel):
    recommendations: list[SurveyRecommendationOutput] = Field(
        description="List of survey recommendations, ordered by priority (highest score first)",
    )
