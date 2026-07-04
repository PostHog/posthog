"""The goal-directed investigate stage: plan goal-grounded HogQL questions, execute them
deterministically, and hand structured findings to the existing synthesize call.

Stage LLM budget, enforced structurally: `plan_investigation` is the stage's only unconditional
LLM call site (synthesis stays the pipeline's other one), a failed step gets at most one repair
call (the ai_subscription fix loop, halved), and result summaries are deterministic renderings of
the executor's output — no LLM ever narrates findings, so more steps cost query execution, not a
third synthesis-shaped call.
"""

import time
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantHogQLQuery

from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError, ResolutionError

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.generation.prompts import (
    INVESTIGATION_PLAN_PROMPT,
    INVESTIGATION_REPAIR_PROMPT,
    sanitize_for_prompt,
)
from products.pulse.backend.sources.anchored_insights import resolve_metric_insight
from products.pulse.backend.sources.base import SourceItem

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool_errors import MaxToolRetryableError

logger = structlog.get_logger(__name__)

# User decision (2026-07-04): room to explore — the justification gate, not the cap, is the
# primary quality control on investigation steps.
MAX_INVESTIGATION_STEPS = 10
INVESTIGATION_MODEL = "gpt-4.1"
_PLANNER_TIMEOUT_SECONDS = 60
_REPAIR_TIMEOUT_SECONDS = 30
_STEP_TIMEOUT_SECONDS = 30
# The stage's slice of the synthesize activity budget (same attempt-budget idea as
# accountability's cap): past the deadline no new step starts; completed findings are kept.
_STAGE_DEADLINE_SECONDS = 180
_RESULT_MAX_CHARS = 1500

# Errors signalling "the query itself is wrong" — a rewrite may help. Everything else (timeouts,
# infra failures) fails the step without a repair call, since a different SELECT won't fix them.
_REPAIRABLE_QUERY_ERRORS: tuple[type[BaseException], ...] = (
    MaxToolRetryableError,
    ExposedHogQLError,
    InternalHogQLError,
)

QUERY_FAILED_PREFIX = "Query failed to run"


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


class HogQLRepair(BaseModel):
    fixed_hogql: str = Field(
        description="One read-only HogQL SELECT (flat, or with a single FROM-subquery) answering the original question."
    )


@dataclass(frozen=True)
class InvestigationFinding:
    """One executed investigation step. `result_summary` is a deterministic rendering of the
    executor's formatted output (truncated in code — the LLM never re-computes numbers); a failed
    step (post-repair) keeps `succeeded=False` with a one-line error note, so the planner's
    question stays visible as a gap. `error_type` and `elapsed_seconds` are the per-step
    diagnostics persisted with the brief for the eval loop."""

    question: str
    hogql: str
    result_summary: str
    succeeded: bool
    error_type: str | None = None
    elapsed_seconds: float = 0.0


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


async def execute_investigation(*, team: Team, user: User, steps: list[PlannedStep]) -> list[InvestigationFinding]:
    """Run the planned steps deterministically, sequentially, inside the stage deadline.

    Sequential on purpose: the deadline check before each step is what lets the stage stop
    starting work while keeping every completed finding — the accountability attempt-budget
    pattern applied to wall-clock time.
    """
    if not steps:
        return []
    executor = AssistantQueryExecutor(team, datetime.now(tz=UTC), user=user)
    stage_started = time.monotonic()
    findings: list[InvestigationFinding] = []
    for index, step in enumerate(steps):
        if time.monotonic() - stage_started >= _STAGE_DEADLINE_SECONDS:
            logger.warning(
                "pulse_investigation_deadline_reached",
                team_id=team.id,
                executed=len(findings),
                skipped=len(steps) - index,
            )
            break
        findings.append(await _run_step(executor, team, user, step))
    return findings


async def _run_step(
    executor: AssistantQueryExecutor, team: Team, user: User, step: PlannedStep
) -> InvestigationFinding:
    step_started = time.monotonic()
    hogql = step.hogql
    exc: BaseException
    try:
        summary = await _run_hogql(executor, hogql)
        return _finding(step, hogql, summary, step_started, succeeded=True)
    except Exception as first_exc:
        exc = first_exc
    if isinstance(exc, _REPAIRABLE_QUERY_ERRORS):
        repaired = await _request_hogql_repair(team=team, user=user, step=step, exc=exc)
        if repaired and repaired.strip() != hogql.strip():
            hogql = repaired
            try:
                summary = await _run_hogql(executor, hogql)
                return _finding(step, hogql, summary, step_started, succeeded=True)
            except Exception as second_exc:
                exc = second_exc
    error_type = type(exc).__name__
    logger.warning("pulse_investigation_step_failed", team_id=team.id, error_type=error_type, exc_info=exc)
    # Type only — ClickHouse errors can echo team-scoped identifiers. An explicit failure note,
    # distinct from an empty result, so synthesis can report the gap instead of "no data".
    return _finding(
        step, hogql, f"{QUERY_FAILED_PREFIX} ({error_type}).", step_started, succeeded=False, error_type=error_type
    )


def _finding(
    step: PlannedStep,
    hogql: str,
    result_summary: str,
    step_started: float,
    *,
    succeeded: bool,
    error_type: str | None = None,
) -> InvestigationFinding:
    return InvestigationFinding(
        question=step.question,
        hogql=hogql,
        result_summary=result_summary,
        succeeded=succeeded,
        error_type=error_type,
        elapsed_seconds=round(time.monotonic() - step_started, 2),
    )


async def _run_hogql(executor: AssistantQueryExecutor, hogql: str) -> str:
    formatted, _ = await asyncio.wait_for(
        executor.arun_and_format_query(AssistantHogQLQuery(query=hogql)),
        timeout=_STEP_TIMEOUT_SECONDS,
    )
    # The deterministic result summary: the executor's own formatting, truncated in code.
    return formatted[:_RESULT_MAX_CHARS]


async def _request_hogql_repair(*, team: Team, user: User, step: PlannedStep, exc: BaseException) -> str | None:
    # Forward the message for exposed errors and ResolutionError (they describe the query the
    # planner wrote — what the fixer needs); other internal errors stay type-only, mirroring the
    # ai_subscription leak-risk analysis.
    error_message = str(exc) if isinstance(exc, ExposedHogQLError | ResolutionError) else type(exc).__name__
    llm = MaxChatOpenAI(
        model=INVESTIGATION_MODEL,
        timeout=_REPAIR_TIMEOUT_SECONDS,
        max_retries=1,
        user=user,
        team=team,
        billable=True,
        posthog_properties={"ai_product": "pulse", "ai_feature": "goal_investigation_repair"},
    ).with_structured_output(HogQLRepair, method="json_schema", include_raw=False)
    rendered = INVESTIGATION_REPAIR_PROMPT.format(
        question=sanitize_for_prompt(step.question),
        error=sanitize_for_prompt(error_message),
        hogql=step.hogql,
    )
    try:
        # database_sync_to_async (not to_thread): MaxChatOpenAI reads billing/quota from the ORM
        result = await database_sync_to_async(llm.invoke, thread_sensitive=False)([("system", rendered)])
    except Exception:
        logger.warning("pulse_investigation_repair_failed", team_id=team.id, exc_info=True)
        return None
    if not isinstance(result, HogQLRepair):
        return None
    return result.fixed_hogql.strip() or None


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
