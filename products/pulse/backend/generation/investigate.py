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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantHogQLQuery

from posthog.hogql.escape_sql import escape_hogql_string

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.generation.prompts import (
    INVESTIGATION_PLAN_PROMPT,
    INVESTIGATION_REPAIR_PROMPT,
    REPLAY_PLAN_PROMPT,
    sanitize_for_prompt,
)
from products.pulse.backend.sources.base import SourceItem

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool_errors import REPAIRABLE_HOGQL_QUERY_ERRORS, safe_error_message_for_llm

if TYPE_CHECKING:
    from ee.hogai.session_summaries.session_group.patterns import (
        EnrichedSessionGroupSummaryPattern,
        EnrichedSessionGroupSummaryPatternsList,
    )

logger = structlog.get_logger(__name__)

# User decision (2026-07-04): room to explore — the prompt-side justification requirement, not
# the cap, is the primary quality control on investigation steps.
MAX_INVESTIGATION_STEPS = 10
# Tighter than the overall cap: every clicks step re-scans the $autocapture window, so a
# scheduled brief must not be able to run that scan MAX_INVESTIGATION_STEPS times.
MAX_CLICKS_STEPS = 3
# The replay-patterns tool runs in its own workflow activity (group summarization takes minutes,
# far past the investigate stage deadline), so exactly one replay per brief is the cost rail: each
# replay step samples up to _MAX_REPLAY_SESSIONS recordings and drives a multi-pass group summary.
MAX_REPLAY_STEPS = 1
# Cap on the sessions handed to the group summary. Above GROUP_SUMMARIES_MIN_SESSIONS (5) the
# summary runs in cross-session pattern mode; below it there is too little to generalize.
_MAX_REPLAY_SESSIONS = 20
_MIN_REPLAY_SESSIONS = 5
# Top patterns rendered into the finding's result_summary (deterministic, strongest first).
_REPLAY_PATTERNS_IN_SUMMARY = 5
# One example session cited per rendered pattern — the player link is the evidence a digest can't attach.
_REPLAY_EXAMPLES_PER_PATTERN = 1
INVESTIGATION_MODEL = "gpt-4.1"
_PLANNER_TIMEOUT_SECONDS = 60
_REPAIR_TIMEOUT_SECONDS = 30
_STEP_TIMEOUT_SECONDS = 30
# The stage's slice of the synthesize activity budget (same attempt-budget idea as
# accountability's cap): past the deadline no new step starts; completed findings are kept.
_STAGE_DEADLINE_SECONDS = 180
# Flat per-step cap (vs the ai_subscription sibling's scaled per-plan budget): with at most 10
# steps the stage deadline, not prompt size, is the effective bound.
_RESULT_MAX_CHARS = 1500
# Appended when a summary is clipped so neither the synthesize LLM nor a reader mistakes a
# clipped partial number for a complete result.
_TRUNCATION_SENTINEL = "\n…(truncated)"
# Mirrors the planner-side bound on PlannedStep.hogql so a repair can't silently outgrow it.
_HOGQL_MAX_LENGTH = 5000
_URL_PATTERN_MAX_LENGTH = 500
_SELECTOR_HINT_MAX_LENGTH = 200
_EVENT_NAME_MAX_LENGTH = 200
# Row cap for the clicks tool's query — the summary is a top-elements digest, not a dump.
_CLICKS_TOP_ROWS = 15

QUERY_FAILED_PREFIX = "Query failed to run"


class PlannedStep(BaseModel):
    tool: Literal["hogql", "clicks", "replay_patterns"] = Field(
        default="hogql",
        description=(
            "Which tool runs this step: 'hogql' executes the step's own hogql; 'clicks' summarizes "
            "click density (top clicked elements) for pages matching url_pattern; 'replay_patterns' "
            "extracts behavioral patterns from real sessions around a movement (own workflow activity)."
        ),
    )
    question: str = Field(max_length=500, description="The plain-English question this query answers for the team.")
    justification: str = Field(
        max_length=500,
        description="How the answer materially informs the stated goal. Required — steps without it are dropped.",
    )
    hogql: str = Field(
        default="",
        max_length=_HOGQL_MAX_LENGTH,
        description="For 'hogql' steps: one read-only HogQL SELECT over the events table. Leave empty for 'clicks' steps.",
    )
    url_pattern: str = Field(
        default="",
        max_length=_URL_PATTERN_MAX_LENGTH,
        description=(
            "For 'clicks' steps: a regular expression matched against the page URL, "
            "e.g. 'https://app.example.com/insights.*'. Leave empty for 'hogql' steps."
        ),
    )
    selector_hint: str = Field(
        default="",
        max_length=_SELECTOR_HINT_MAX_LENGTH,
        description=(
            "Optional, 'clicks' steps only: count only clicks whose DOM element chain contains this "
            "substring (e.g. a CSS class or tag name)."
        ),
    )
    event_name: str = Field(
        default="",
        max_length=_EVENT_NAME_MAX_LENGTH,
        description=(
            "Optional, 'replay_patterns' steps only: require this event in a session for it to be "
            "sampled (e.g. '$rageclick'). Combine with url_pattern, or use either alone."
        ),
    )


class InvestigationPlan(BaseModel):
    # No schema-level cap: the cap is enforced in code so a non-compliant model output degrades
    # to a truncated plan instead of a failed structured-output parse.
    steps: list[PlannedStep] = Field(description=f"At most {MAX_INVESTIGATION_STEPS} justified investigation steps.")


class HogQLRepair(BaseModel):
    fixed_hogql: str = Field(
        max_length=_HOGQL_MAX_LENGTH,
        description="One read-only HogQL SELECT (flat, or with a single FROM-subquery) answering the original question.",
    )


@dataclass(frozen=True)
class InvestigationFinding:
    """One executed investigation step. `result_summary` is a deterministic rendering of the
    executor's formatted output (truncated in code — the LLM never re-computes numbers); a failed
    step (post-repair) keeps `succeeded=False` with a one-line error note, so the planner's
    question stays visible as a gap. `citations` carries code-generated evidence refs
    (`session:<id>` for replay_patterns findings); hogql/clicks findings leave it empty."""

    question: str
    hogql: str
    result_summary: str
    succeeded: bool
    citations: list[str] = field(default_factory=list)


async def run_investigation(
    *, team: Team, user: User, goal_status: GoalStatus, items: list[SourceItem], period_days: int
) -> list[InvestigationFinding]:
    """The whole stage: plan, then execute. An empty plan (including every planner failure)
    means no investigation — the caller ships the brief without one."""
    steps = await database_sync_to_async(plan_investigation, thread_sensitive=False)(
        team=team, user=user, goal_status=goal_status, items=items, period_days=period_days
    )
    return await execute_investigation(team=team, user=user, steps=steps, period_days=period_days)


def plan_investigation(
    *, team: Team, user: User, goal_status: GoalStatus, items: list[SourceItem], period_days: int
) -> list[PlannedStep]:
    """One planner LLM call proposing goal-grounded HogQL questions — the investigate stage's
    only unconditional LLM call; synthesis stays the pipeline's other one.

    Best-effort by design: any planner failure (prompt rendering, LLM error, malformed output)
    degrades to an empty plan so the brief ships without an investigation, never fails because
    of one.
    """
    try:
        rendered = INVESTIGATION_PLAN_PROMPT.format(
            goal_text=sanitize_for_prompt(goal_status.goal),
            metric_line=_render_metric_line(goal_status),
            max_steps=MAX_INVESTIGATION_STEPS,
            max_clicks_steps=MAX_CLICKS_STEPS,
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
        result = llm.invoke([("system", rendered)])
    except Exception:
        logger.exception("pulse_investigation_plan_failed", team_id=team.id)
        return []
    if not isinstance(result, InvestigationPlan):
        logger.error("pulse_investigation_plan_malformed", team_id=team.id, output_type=type(result).__name__)
        return []
    return _apply_plan_gates(team, result.steps)


def _step_tool_input(step: PlannedStep) -> str:
    # The one field the step's tool cannot run without — blank means the step is unexecutable.
    return step.hogql if step.tool == "hogql" else step.url_pattern


def _apply_plan_gates(team: Team, steps: list[PlannedStep]) -> list[PlannedStep]:
    # The hard caps are code-enforced regardless of model output. The blank-field check is only a
    # backstop — the justification gate proper is the prompt-side forcing function (a model that
    # pads justifications sails through here; the eval loop is what catches that). replay_patterns
    # steps are dropped: they run in their own activity via plan_replay_patterns, never inline.
    kept: list[PlannedStep] = []
    clicks_kept = 0
    for step in steps:
        if step.tool == "replay_patterns":
            continue
        if not (step.question.strip() and step.justification.strip() and _step_tool_input(step).strip()):
            continue
        if step.tool == "clicks":
            if clicks_kept >= MAX_CLICKS_STEPS:
                continue
            clicks_kept += 1
        kept.append(step)
    if len(kept) < len(steps):
        logger.info("pulse_investigation_steps_dropped", team_id=team.id, dropped=len(steps) - len(kept))
    return kept[:MAX_INVESTIGATION_STEPS]


def _apply_replay_plan_gates(team: Team, steps: list[PlannedStep]) -> list[PlannedStep]:
    # The replay planner's own gate: keep only anchored replay_patterns steps, capped at
    # MAX_REPLAY_STEPS. A step needs a question, a justification, and at least one anchor
    # (url_pattern or event_name) — the surface the sessions are sampled around.
    kept: list[PlannedStep] = []
    for step in steps:
        if step.tool != "replay_patterns":
            continue
        if not (step.question.strip() and step.justification.strip()):
            continue
        if not (step.url_pattern.strip() or step.event_name.strip()):
            continue
        kept.append(step)
        if len(kept) >= MAX_REPLAY_STEPS:
            break
    if len(kept) < len(steps):
        logger.info("pulse_replay_steps_dropped", team_id=team.id, dropped=len(steps) - len(kept))
    return kept


def _render_metric_line(goal_status: GoalStatus) -> str:
    # Mirrors synthesize's goal block degradation: a qualitative goal gets no metric line, an
    # unreadable configured metric gets an honest one. metric_event (carried on GoalStatus from
    # the goal collector's insight read) tells the planner what the metric measures so it can
    # investigate the metric itself.
    if goal_status.metric_state == "none":
        return ""
    if goal_status.metric_state == "unavailable":
        return (
            "\nA goal metric is configured but could not be read this period — that itself may be worth investigating."
        )
    measures = (
        f" (a trends insight over '{sanitize_for_prompt(goal_status.metric_event)}' events)"
        if goal_status.metric_event
        else ""
    )
    delta = f" ({goal_status.delta_pct:+.1f}% vs the prior period)" if goal_status.delta_pct is not None else ""
    return (
        f"\nGoal metric '{sanitize_for_prompt(goal_status.metric_label or '')}'{measures}: "
        f"now {goal_status.current_rate}, previously {goal_status.previous_rate}{delta}."
    )


async def execute_investigation(
    *, team: Team, user: User, steps: list[PlannedStep], period_days: int
) -> list[InvestigationFinding]:
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
        if step.tool == "clicks":
            findings.append(await _run_clicks_step(executor, team, step, period_days))
        else:
            findings.append(await _run_step(executor, team, user, step))
    return findings


def build_clicks_query(url_pattern: str, selector_hint: str, period_days: int) -> str:
    """The clicks tool's deterministic HogQL: top clicked elements ($autocapture) on pages whose
    URL matches the planner's pattern.

    An approximation by design: the heatmaps product's dedicated table stores pure coordinate
    geometry (no element identity), and web_analytics exposes no public server-side entry for
    element-level click summaries — so this mirrors its Max tool's $autocapture cross-reference
    (AUTOCAPTURE_ELEMENTS_QUERY in products/web_analytics/backend/max_tools.py, url_pattern
    semantics from its heatmaps API). A heatmaps facade capability is the recorded ask.
    """
    selector_filter = (
        f"\n  AND elements_chain ILIKE {escape_hogql_string('%' + selector_hint + '%')}" if selector_hint else ""
    )
    return (
        "SELECT properties.$el_text AS element_text, count() AS clicks\n"
        "FROM events\n"
        "WHERE event = '$autocapture'\n"
        f"  AND match(properties.$current_url, {escape_hogql_string(url_pattern)})\n"
        f"  AND timestamp >= now() - INTERVAL {period_days} DAY\n"
        "  AND notEmpty(properties.$el_text)"
        f"{selector_filter}\n"
        "GROUP BY element_text\n"
        "ORDER BY clicks DESC\n"
        f"LIMIT {_CLICKS_TOP_ROWS}"
    )


async def _run_clicks_step(
    executor: AssistantQueryExecutor, team: Team, step: PlannedStep, period_days: int
) -> InvestigationFinding:
    # No repair branch on purpose: the query is code-built, so there is no planner HogQL to fix —
    # a failed clicks step is a gap, not a repair candidate.
    hogql = build_clicks_query(step.url_pattern, step.selector_hint, period_days)
    header = (
        f"Top clicked elements on pages matching '{step.url_pattern}' (last {period_days} days, $autocapture clicks):"
    )
    try:
        summary = await _run_hogql(executor, hogql)
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("pulse_investigation_clicks_step_failed", team_id=team.id, error_type=error_type, exc_info=exc)
        return InvestigationFinding(
            question=step.question,
            hogql=hogql,
            result_summary=f"{QUERY_FAILED_PREFIX} ({error_type}).",
            succeeded=False,
        )
    return InvestigationFinding(
        question=step.question, hogql=hogql, result_summary=f"{header}\n{summary}", succeeded=True
    )


async def _run_step(
    executor: AssistantQueryExecutor, team: Team, user: User, step: PlannedStep
) -> InvestigationFinding:
    hogql = step.hogql
    exc: BaseException
    try:
        summary = await _run_hogql(executor, hogql)
        return InvestigationFinding(question=step.question, hogql=hogql, result_summary=summary, succeeded=True)
    except Exception as first_exc:
        exc = first_exc
    if isinstance(exc, REPAIRABLE_HOGQL_QUERY_ERRORS):
        repaired = await _request_hogql_repair(team=team, user=user, step=step, exc=exc)
        if repaired and repaired.strip() != hogql.strip():
            hogql = repaired
            try:
                summary = await _run_hogql(executor, hogql)
                return InvestigationFinding(question=step.question, hogql=hogql, result_summary=summary, succeeded=True)
            except Exception as second_exc:
                exc = second_exc
    error_type = type(exc).__name__
    logger.warning("pulse_investigation_step_failed", team_id=team.id, error_type=error_type, exc_info=exc)
    # Type only — ClickHouse errors can echo team-scoped identifiers. An explicit failure note,
    # distinct from an empty result, so synthesis can report the gap instead of "no data".
    return InvestigationFinding(
        question=step.question,
        hogql=hogql,
        result_summary=f"{QUERY_FAILED_PREFIX} ({error_type}).",
        succeeded=False,
    )


async def _run_hogql(executor: AssistantQueryExecutor, hogql: str) -> str:
    formatted, _ = await asyncio.wait_for(
        executor.arun_and_format_query(AssistantHogQLQuery(query=hogql)),
        timeout=_STEP_TIMEOUT_SECONDS,
    )
    # The deterministic result summary: the executor's own formatting, truncated in code.
    if len(formatted) > _RESULT_MAX_CHARS:
        return formatted[:_RESULT_MAX_CHARS] + _TRUNCATION_SENTINEL
    return formatted


async def _request_hogql_repair(*, team: Team, user: User, step: PlannedStep, exc: BaseException) -> str | None:
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
        # safe_error_message_for_llm carries the leak-risk forwarding rule (message only for
        # exposed/resolution errors, type name otherwise).
        error=sanitize_for_prompt(safe_error_message_for_llm(exc)),
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


# ---------------------------------------------------------------------------
# The replay-patterns stage: watch real sessions around a movement.
#
# A SEPARATE workflow activity from the HogQL investigation (group summarization runs minutes,
# far past the 180s investigate stage deadline), planned by its own single LLM call. Structurally
# bounded: 1 planner call + at most MAX_REPLAY_STEPS steps, each sampling ≤_MAX_REPLAY_SESSIONS
# recordings into one upstream-throttled, cached group summary. Best-effort throughout — a planner
# or step failure yields no finding, never fails the brief.
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


async def run_replay_investigation(
    *, team: Team, user: User, goal_text: str, movements: list[SourceItem], period_days: int
) -> list[InvestigationFinding]:
    """Plan (one LLM call), then for each planned step sample sessions around the movement and
    extract cross-session patterns. Returns [] when the planner requests no replay."""
    steps = await database_sync_to_async(plan_replay_patterns, thread_sensitive=False)(
        team=team, user=user, goal_text=goal_text, movements=movements, period_days=period_days
    )
    findings: list[InvestigationFinding] = []
    for step in steps:
        findings.append(await _run_replay_patterns_step(team=team, user=user, step=step, period_days=period_days))
    return findings


def plan_replay_patterns(
    *, team: Team, user: User, goal_text: str, movements: list[SourceItem], period_days: int
) -> list[PlannedStep]:
    """One planner LLM call deciding whether watching sessions around a movement would explain it.
    Best-effort: any failure (prompt rendering, LLM error, malformed output) degrades to an empty
    plan so the brief ships without a replay analysis, never fails because of one."""
    if not movements:
        return []
    try:
        rendered = REPLAY_PLAN_PROMPT.format(
            goal_text=sanitize_for_prompt(goal_text),
            period_days=period_days,
            max_steps=MAX_REPLAY_STEPS,
            movements_block=_render_items_for_planner(movements),
        )
        llm = MaxChatOpenAI(
            model=INVESTIGATION_MODEL,
            timeout=_PLANNER_TIMEOUT_SECONDS,
            max_retries=1,
            user=user,
            team=team,
            billable=True,
            posthog_properties={"ai_product": "pulse", "ai_feature": "goal_replay_plan"},
        ).with_structured_output(InvestigationPlan, method="json_schema", include_raw=False)
        result = llm.invoke([("system", rendered)])
    except Exception:
        logger.exception("pulse_replay_plan_failed", team_id=team.id)
        return []
    if not isinstance(result, InvestigationPlan):
        logger.error("pulse_replay_plan_malformed", team_id=team.id, output_type=type(result).__name__)
        return []
    return _apply_replay_plan_gates(team, result.steps)


def _replay_gap(step: PlannedStep, note: str) -> InvestigationFinding:
    # A failed/empty replay step is a gap, not data — distinct from a successful pattern finding.
    return InvestigationFinding(question=step.question, hogql="", result_summary=note, succeeded=False, citations=[])


async def _run_replay_patterns_step(
    *, team: Team, user: User, step: PlannedStep, period_days: int
) -> InvestigationFinding:
    try:
        session_ids = await database_sync_to_async(_resolve_replay_session_ids, thread_sensitive=False)(
            team, step, period_days
        )
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("pulse_replay_session_fetch_failed", team_id=team.id, error_type=error_type, exc_info=exc)
        return _replay_gap(step, f"Could not fetch sessions to watch ({error_type}).")
    if len(session_ids) < _MIN_REPLAY_SESSIONS:
        return _replay_gap(
            step,
            f"Only {len(session_ids)} session(s) matched the movement's surface — too few to generalize "
            f"(need at least {_MIN_REPLAY_SESSIONS}).",
        )
    try:
        patterns = await _summarize_session_group(
            session_ids=session_ids, user=user, team=team, period_days=period_days, title=step.question
        )
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("pulse_replay_summary_failed", team_id=team.id, error_type=error_type, exc_info=exc)
        return _replay_gap(step, f"Replay pattern analysis did not complete ({error_type}).")
    summary, citations = _render_replay_patterns(patterns, len(session_ids))
    return InvestigationFinding(
        question=step.question, hogql="", result_summary=summary, succeeded=True, citations=citations
    )


def _build_replay_recording_filters(url_pattern: str, event_name: str) -> dict:
    # The universal-filter dict shape convert_filters_to_recordings_query expects: a url anchor
    # becomes a `visited_page` recording property (matched over the session's URLs, not a single
    # $pageview), an event anchor becomes an events entry the session must contain.
    values: list[dict] = []
    if url_pattern:
        values.append({"type": "recording", "key": "visited_page", "value": url_pattern, "operator": "icontains"})
    if event_name:
        values.append({"type": "events", "id": event_name, "name": event_name, "order": 0})
    return {
        "filter_test_accounts": True,
        "filter_group": {"type": "AND", "values": [{"type": "AND", "values": values}]},
    }


def _resolve_replay_session_ids(team: Team, step: PlannedStep, period_days: int) -> list[str]:
    # noqa keeps the session-replay/temporal stack off the pulse import path — loaded only when a replay step runs.
    from posthog.temporal.session_replay.summarization_sweep.session_candidates import (  # noqa: PLC0415
        fetch_recent_session_ids,
    )

    filters = _build_replay_recording_filters(step.url_pattern.strip(), step.event_name.strip())
    lookback_minutes = period_days * 24 * 60
    # sample_rate=1.0: the url/event anchor already narrows to the movement's segment, so the
    # ~20-session cap is the sampling — a fractional rate on top would routinely starve the group.
    session_ids = fetch_recent_session_ids(
        team, lookback_minutes, sample_rate=1.0, recording_filters=filters, limit=_MAX_REPLAY_SESSIONS
    )
    return session_ids[:_MAX_REPLAY_SESSIONS]


async def _summarize_session_group(
    *, session_ids: list[str], user: User, team: Team, period_days: int, title: str
) -> "EnrichedSessionGroupSummaryPatternsList":
    # noqa keeps the heavy session-summary/temporal stack off the pulse import path — loaded only when a replay step runs.
    from posthog.temporal.session_replay.session_summary_group.types import SessionSummaryStreamUpdate  # noqa: PLC0415
    from posthog.temporal.session_replay.session_summary_group.workflow import (  # noqa: PLC0415
        execute_summarize_session_group,
    )

    max_timestamp = datetime.now(tz=UTC)
    min_timestamp = max_timestamp - timedelta(days=period_days)
    patterns: EnrichedSessionGroupSummaryPatternsList | None = None
    # The generator starts a group-summary workflow and streams progress; the FINAL_RESULT payload
    # is (patterns, group_summary_id, failed). The activity's own timeout is the hard ceiling —
    # group summaries are upstream-throttled and cached, so no second cache is added here.
    async for update, payload in execute_summarize_session_group(
        session_ids=session_ids,
        user=user,
        team=team,
        min_timestamp=min_timestamp,
        max_timestamp=max_timestamp,
        summary_title=title,
    ):
        if update == SessionSummaryStreamUpdate.FINAL_RESULT and isinstance(payload, tuple):
            patterns = payload[0]
    if patterns is None:
        raise RuntimeError("session group summary produced no final result")
    return patterns


def _example_session_ids(pattern: "EnrichedSessionGroupSummaryPattern") -> list[str]:
    ids: list[str] = []
    for segment in pattern.events[:_REPLAY_EXAMPLES_PER_PATTERN]:
        session_id = segment.target_event.session_id
        if session_id:
            ids.append(session_id)
    return ids


def _render_replay_patterns(
    patterns: "EnrichedSessionGroupSummaryPatternsList", session_count: int
) -> tuple[str, list[str]]:
    # Deterministic rendering: severity-then-reach order, code-formatted lines, code-collected
    # `session:<id>` citations. The LLM never narrates or re-counts.
    ordered = sorted(
        patterns.patterns,
        key=lambda p: (_SEVERITY_ORDER.get(p.severity.value, len(_SEVERITY_ORDER)), -p.stats.sessions_affected),
    )
    top = ordered[:_REPLAY_PATTERNS_IN_SUMMARY]
    if not top:
        return (f"Watched {session_count} sessions; no recurring behavioral pattern stood out.", [])
    lines = [f"Watched {session_count} sessions. Recurring patterns (most severe first):"]
    citations: list[str] = []
    seen: set[str] = set()
    for pattern in top:
        name = sanitize_for_prompt(pattern.pattern_name)
        description = sanitize_for_prompt(pattern.pattern_description)
        lines.append(
            f"- {name}: {pattern.stats.sessions_affected}/{session_count} sessions "
            f"({pattern.severity.value} severity) — {description}"
        )
        for session_id in _example_session_ids(pattern):
            if session_id not in seen:
                seen.add(session_id)
                citations.append(f"session:{session_id}")
    summary = "\n".join(lines)
    if len(summary) > _RESULT_MAX_CHARS:
        summary = summary[:_RESULT_MAX_CHARS] + _TRUNCATION_SENTINEL
    return (summary, citations)
