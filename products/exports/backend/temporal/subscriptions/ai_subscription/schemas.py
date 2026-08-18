from typing import Literal, Optional

from pydantic import BaseModel, Field

# Hard cap on AI report query-plan steps — the contract the schema validator, planner prompt, and
# synthesis result budget all key off. Named once here so they can't silently drift apart.
MAX_QUERY_PLAN_STEPS = 25

# Chart budget for one report. Three pictures answer a prompt; ten rebuild the wall of text in a
# new medium, and each one costs a render.
MAX_CHARTS_PER_REPORT = 3
# More series than the legend can carry reads as noise.
MAX_CHART_SERIES = 4
# Two points are a slope, not a shape.
MIN_CHART_ROWS = 3
# Past this the bars stop being separable at the render width.
MAX_CHART_CATEGORIES = 25

# Only displays a planner can pick correctly from column names alone. Table, pie, and map either
# defeat the purpose or need settings it cannot choose.
ChartDisplay = Literal["ActionsLineGraph", "ActionsBar", "ActionsAreaGraph"]


class StepChart(BaseModel):
    display: ChartDisplay = Field(..., description="How to draw the chart.")
    x_column: str = Field(..., max_length=200, description="Result column for the x axis, by its SELECT alias.")
    y_columns: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_CHART_SERIES,
        description="Result columns to plot, by their SELECT aliases.",
    )


class QueryPlanStep(BaseModel):
    description: str = Field(..., max_length=500, description="One-sentence rationale for running this query.")
    query_type: Literal["hogql"] = Field("hogql", description="MVP: always 'hogql'.")
    hogql: str = Field(..., max_length=5000, description="A HogQL SELECT statement scoped to the team's events.")
    chart: Optional[StepChart] = Field(None, description="Set when this step's result is worth showing as a chart.")


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
    # Raw event names whose per-event property schema is folded into context_blob. Persisted in the
    # frozen envelope so the reuse path can rebuild the same property-aware blob the fixer needs.
    relevant_events: list[str] = Field(default_factory=list)


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
