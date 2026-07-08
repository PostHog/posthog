from typing import Literal

from pydantic import BaseModel, Field

# Hard cap on AI report query-plan steps — the contract the schema validator, planner prompt, and
# synthesis result budget all key off. Named once here so they can't silently drift apart.
MAX_QUERY_PLAN_STEPS = 25


class QueryPlanStep(BaseModel):
    description: str = Field(..., max_length=500, description="One-sentence rationale for running this query.")
    query_type: Literal["hogql"] = Field("hogql", description="MVP: always 'hogql'.")
    hogql: str = Field(..., max_length=5000, description="A HogQL SELECT statement scoped to the team's events.")


class QueryPlan(BaseModel):
    overall_intent: str = Field(
        ...,
        max_length=500,
        description="Plain-English summary of what the report will tell the user.",
    )
    steps: list[QueryPlanStep] = Field(..., min_length=1, max_length=MAX_QUERY_PLAN_STEPS)


class EnrichedPromptSpec(BaseModel):
    cleaned_prompt: str
    context_blob: str
    plan: QueryPlan


class HogQLFix(BaseModel):
    fixed_hogql: str = Field(
        ...,
        description="A HogQL SELECT statement (flat, or with a single FROM-subquery) that addresses the original step intent.",
    )


class RelevantEvents(BaseModel):
    events: list[str] = Field(
        default_factory=list,
        description="Event names — copied verbatim from the provided list — relevant to the user's prompt.",
    )
