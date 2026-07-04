import structlog
from pydantic import BaseModel, Field

from posthog.models.team import Team
from posthog.models.user import User

from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.generation.prompts import INVESTIGATION_PLAN_PROMPT, sanitize_for_prompt
from products.pulse.backend.sources.anchored_insights import resolve_metric_insight
from products.pulse.backend.sources.base import SourceItem

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)

# User decision (2026-07-04): room to explore — the justification gate, not the cap, is the
# primary quality control on investigation steps.
MAX_INVESTIGATION_STEPS = 10
INVESTIGATION_MODEL = "gpt-4.1"
_PLANNER_TIMEOUT_SECONDS = 60


class PlannedStep(BaseModel):
    question: str = Field(max_length=500, description="The plain-English question this query answers for the team.")
    justification: str = Field(
        max_length=500,
        description="How the answer materially informs the stated goal. Required — steps without it are dropped.",
    )
    hogql: str = Field(max_length=5000, description="One read-only HogQL SELECT over the events table.")


class InvestigationPlan(BaseModel):
    # No schema-level cap: the cap is enforced in code so a non-compliant model output degrades
    # to a truncated plan instead of a failed structured-output parse.
    steps: list[PlannedStep] = Field(description=f"At most {MAX_INVESTIGATION_STEPS} justified investigation steps.")


def plan_investigation(
    *, team: Team, user: User, goal_status: GoalStatus, items: list[SourceItem], period_days: int
) -> list[PlannedStep]:
    """One planner LLM call proposing goal-grounded HogQL questions — the investigate stage's
    only unconditional LLM call; synthesis stays the pipeline's other one.

    Best-effort by design: any planner failure (LLM error, malformed output) degrades to an
    empty plan so the brief ships without an investigation, never fails because of one.
    """
    rendered = INVESTIGATION_PLAN_PROMPT.format(
        goal_text=sanitize_for_prompt(goal_status.goal),
        metric_line=_render_metric_line(team, goal_status),
        max_steps=MAX_INVESTIGATION_STEPS,
        period_days=period_days,
        items_block=_render_items_for_planner(items),
    )
    llm = MaxChatOpenAI(
        model=INVESTIGATION_MODEL,
        timeout=_PLANNER_TIMEOUT_SECONDS,
        max_retries=1,
        user=user,
        team=team,
        billable=True,
        posthog_properties={"ai_product": "pulse", "ai_feature": "goal_investigation_plan"},
    ).with_structured_output(InvestigationPlan, method="json_schema", include_raw=False)
    try:
        result = llm.invoke([("system", rendered)])
    except Exception:
        logger.exception("pulse_investigation_plan_failed", team_id=team.id)
        return []
    if not isinstance(result, InvestigationPlan):
        logger.error("pulse_investigation_plan_malformed", team_id=team.id, output_type=type(result).__name__)
        return []
    return _apply_plan_gates(team, result.steps)


def _apply_plan_gates(team: Team, steps: list[PlannedStep]) -> list[PlannedStep]:
    # Code-enforced regardless of model compliance: the justification gate (say-less applies to
    # queries too) and the hard step cap.
    kept = [step for step in steps if step.question.strip() and step.justification.strip() and step.hogql.strip()]
    if len(kept) < len(steps):
        logger.info("pulse_investigation_steps_dropped", team_id=team.id, dropped=len(steps) - len(kept))
    return kept[:MAX_INVESTIGATION_STEPS]


def _render_metric_line(team: Team, goal_status: GoalStatus) -> str:
    # Mirrors synthesize's goal block degradation: a qualitative goal gets no metric line, an
    # unreadable configured metric gets an honest one. Adds what the metric measures (resolved
    # from the configured insight's query) so the planner can investigate the metric itself.
    if goal_status.metric_state == "none":
        return ""
    if goal_status.metric_state == "unavailable":
        return (
            "\nA goal metric is configured but could not be read this period — that itself may be worth investigating."
        )
    measures = _metric_query_summary(team, goal_status)
    delta = f" ({goal_status.delta_pct:+.1f}% vs the prior period)" if goal_status.delta_pct is not None else ""
    return (
        f"\nGoal metric '{sanitize_for_prompt(goal_status.metric_label or '')}'{measures}: "
        f"now {goal_status.current_rate}, previously {goal_status.previous_rate}{delta}."
    )


def _metric_query_summary(team: Team, goal_status: GoalStatus) -> str:
    # The goal metric is the insight's first series (goal_metric carries no series_index).
    # Best-effort: a missing/misshapen insight simply adds no "measuring" clause.
    if not goal_status.insight_short_id:
        return ""
    insight = resolve_metric_insight(team, goal_status.insight_short_id)
    if insight is None:
        return ""
    source = (insight.query or {}).get("source") or {}
    series = source.get("series") or []
    first = series[0] if series and isinstance(series[0], dict) else {}
    event = first.get("event")
    if not isinstance(event, str) or not event:
        return ""
    return f" (a trends insight over '{sanitize_for_prompt(event)}' events)"


def _render_items_for_planner(items: list[SourceItem]) -> str:
    # Leaner than synthesize's items block on purpose: the planner needs what happened, not the
    # citation machinery (evidence refs, fingerprint hints). Same render-boundary sanitization.
    if not items:
        return "None gathered."
    blocks = []
    for item in items:
        numbers = ", ".join(f"{k}={v}" for k, v in item.numbers.items())
        blocks.append(
            f"- [{item.source}/{item.kind}] {sanitize_for_prompt(item.title)}"
            + (f" — numbers: {numbers}" if numbers else "")
            + f" — {sanitize_for_prompt(item.description)}"
        )
    return "\n".join(blocks)
