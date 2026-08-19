from typing import Literal, Optional

from pydantic import BaseModel, Field

# Hard cap on AI report query-plan steps — the contract the schema validator, planner prompt, and
# synthesis result budget all key off. Named once here so they can't silently drift apart.
MAX_QUERY_PLAN_STEPS = 25

# Chart budget for one report. Each chart costs a browserless render and a second execution of its
# query, and the render phase has to finish inside _CHART_PHASE_BUDGET_SECONDS. Six is two worst-case
# render waves at _MAX_CONCURRENT_RENDERS. The planner ranks; the highest-importance six render.
MAX_CHARTS_PER_REPORT = 6
# Importance scale the planner scores each chart on. Small and bounded so the values stay comparable
# across steps rather than drifting into arbitrary precision.
MIN_CHART_IMPORTANCE = 1
MAX_CHART_IMPORTANCE = 5
# More series than the legend can carry reads as noise.
MAX_CHART_SERIES = 4
# Two points are a slope, not a shape.
MIN_CHART_ROWS = 3
# A bar chart compares categories, so one bar is not a chart. Planners do emit single-row scalar
# queries (a rate, a growth percentage) and mark them chartable.
MIN_CHART_CATEGORIES = 2
# Past this the bars stop being separable at the render width.
MAX_CHART_CATEGORIES = 25
# A chart caption is a label, not a sentence. Long enough for "New signups per day, by plan".
MAX_CHART_TITLE_LENGTH = 80

# Only displays a planner can pick correctly from column names alone. Table, pie, and map either
# defeat the purpose or need settings it cannot choose.
# Displays whose x axis is a continuous run of points, so a chart of one or two rows reads as noise.
CONTINUOUS_CHART_DISPLAYS = frozenset({"ActionsLineGraph", "ActionsAreaGraph"})
ALLOWED_CHART_DISPLAYS = CONTINUOUS_CHART_DISPLAYS | {"ActionsBar"}


class StepChart(BaseModel):
    """A chart the planner asked for.

    Deliberately free of bounds constraints. A chart is a decoration, and every layer below treats
    one as droppable, but this model is part of QueryPlan: a `le=5` or a `max_length` here turns a
    bad importance or an over-long title into a whole-plan validation error, which surfaces as a
    rejected prompt and auto-disables the subscription. The descriptions still steer the planner,
    and `validate_chart` enforces the real limits where dropping costs only the picture.
    """

    display: str = Field(
        ...,
        description=f"How to draw the chart. One of: {', '.join(sorted(ALLOWED_CHART_DISPLAYS))}.",
    )
    title: Optional[str] = Field(
        None,
        description=f"Short label shown above the chart, at most {MAX_CHART_TITLE_LENGTH} characters.",
    )
    importance: int = Field(
        MIN_CHART_IMPORTANCE,
        description=(
            f"How much this chart matters to the reader, {MIN_CHART_IMPORTANCE} to "
            f"{MAX_CHART_IMPORTANCE}, with {MAX_CHART_IMPORTANCE} the most important."
        ),
    )
    x_column: str = Field(..., description="Result column for the x axis, by its SELECT alias.")
    y_columns: list[str] = Field(
        ...,
        description=f"Result columns to plot, by their SELECT aliases. At most {MAX_CHART_SERIES}.",
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
