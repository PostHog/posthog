from typing import Literal, Optional

from pydantic import BaseModel, Field

from posthog.schema import ChartDisplayType

from ee.tasks.subscriptions.subscription_utils import MAX_INSIGHTS

# Hard cap on AI report query-plan steps — the contract the schema validator, planner prompt, and
# synthesis result budget all key off. Named once here so they can't silently drift apart.
MAX_QUERY_PLAN_STEPS = 25

# Bound to the dashboard subscription insight cap so the two kinds of subscription report
# show the same number of pictures.
MAX_CHARTS_PER_REPORT = MAX_INSIGHTS
MIN_CHART_IMPORTANCE = 1
MAX_CHART_IMPORTANCE = 5
MAX_CHART_SERIES = 4
MIN_CHART_ROWS = 3
MIN_CHART_CATEGORIES = 2
MAX_CHART_CATEGORIES = 25
MAX_CHART_TITLE_LENGTH = 80

CONTINUOUS_CHART_DISPLAYS = frozenset({ChartDisplayType.ACTIONS_LINE_GRAPH, ChartDisplayType.ACTIONS_AREA_GRAPH})
ALLOWED_CHART_DISPLAYS: frozenset[str] = CONTINUOUS_CHART_DISPLAYS | {ChartDisplayType.ACTIONS_BAR}


class StepChart(BaseModel):
    """A chart the planner asked for.

    Carries no bounds constraints on purpose. It is part of QueryPlan, so a bound here would fail
    the whole plan over one bad chart. `validate_chart` enforces the limits, where a violation
    costs only the picture.
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
            f"{MAX_CHART_IMPORTANCE}, with {MAX_CHART_IMPORTANCE} the most important. "
            f"A report shows every chart you ask for, up to {MAX_CHARTS_PER_REPORT}. Only when you "
            "ask for more than that are the lowest scores dropped, so score honestly."
        ),
    )
    x_column: str = Field(
        ...,
        description=(
            "The column to spread the chart along the bottom, named by its SELECT alias. "
            "Usually a day or a category name."
        ),
    )
    y_columns: list[str] = Field(
        ...,
        description=(
            "The columns to draw as lines or bars, named by their SELECT aliases. Each one must "
            f"hold numbers. At most {MAX_CHART_SERIES}."
        ),
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
