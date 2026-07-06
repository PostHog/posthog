import uuid
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Optional, Union

import structlog

from posthog.schema import AssistantHogQLQuery

from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError, ResolutionError

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.security.llm_prompt_sanitization import strip_llm_framing_markers
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation
from posthog.sync import database_sync_to_async

from products.exports.backend.temporal.subscriptions.ai_subscription.prompts import (
    AI_SUBSCRIPTION_SYNTHESIS_PROMPT,
    HOGQL_FIX_PROMPT,
    HOGQL_FIX_PROMPT_NAME,
    SYNTHESIS_PROMPT_NAME,
    render_prompt,
    resolve_prompt,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    MAX_QUERY_PLAN_STEPS,
    EnrichedPromptSpec,
    HogQLFix,
    QueryPlanStep,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    DEFAULT_PLANNER_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    PromptRejectedError,
    build_enriched_prompt,
)

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool_errors import MaxToolRetryableError

logger = structlog.get_logger(__name__)

# Wall-clock bounds for the in-band LLM + HogQL pipeline. The caller's outer deadline (Temporal
# activity timeout for scheduled, request timeout for ad-hoc) is the ultimate cap; these prevent a
# single slow upstream from soaking it.
_SYNTHESIS_LLM_TIMEOUT_SECONDS = 90.0
_HOGQL_STEP_TIMEOUT_SECONDS = 60.0
# Backstop length cap on a single step's formatted results before they enter the synthesis prompt.
# The executor already truncates; this is defense-in-depth against a giant value.
_QUERY_RESULT_MAX_CHARS = 50_000
# Total result budget across all steps entering the synthesis prompt: without it, the per-step backstop
# alone would let MAX_QUERY_PLAN_STEPS x _QUERY_RESULT_MAX_CHARS into one synthesis call. `per_step_cap`
# derives from this — the outer min() lets small plans keep the full per-step backstop, while the floor
# (the budget split evenly across a full-size plan) guarantees each step a minimum so a max-size plan
# can't starve any single step. Deriving the floor from the cap keeps the total within budget at any cap.
_SYNTHESIS_RESULTS_CHAR_BUDGET = 200_000
_MIN_STEP_RESULT_CHARS = _SYNTHESIS_RESULTS_CHAR_BUDGET // MAX_QUERY_PLAN_STEPS

# The marker a failed step renders. The synthesis prompt keys off it to report "could not be computed"
# instead of "no data"; it's injected into that prompt (the {{{failure_marker}}} placeholder) from this
# same constant in `_synthesize`, so the rendered marker and the prompt instruction can't drift apart.
QUERY_FAILED_PREFIX = "Query failed to run"

# Per-step query-fix budget: the planner occasionally emits HogQL that fails to parse, so we feed the
# error back and ask for a rewrite rather than dropping the step. Worst case per step is one original
# run plus _MAX_QUERY_FIX_RETRIES × (fix LLM + rerun); steps run concurrently, bounded by
# _MAX_CONCURRENT_STEPS.
_MAX_QUERY_FIX_RETRIES = 2
_FIX_LLM_TIMEOUT_SECONDS = 30.0

# The planner may emit up to MAX_QUERY_PLAN_STEPS steps; bound how many run their ClickHouse query at
# once so one report delivery can't fan out into dozens of simultaneous scans. Steps beyond the cap
# queue and run as slots free up — every step still executes.
_MAX_CONCURRENT_STEPS = 5

# Errors signalling "the query itself is wrong" — rewriting may help. Everything else (timeouts, infra
# failures, generic exceptions) falls through to the "_Query failed to run_" placeholder without retrying,
# since a different SELECT won't fix a ClickHouse outage or a heartbeat timeout.
_RETRYABLE_QUERY_ERRORS: tuple[type[BaseException], ...] = (
    MaxToolRetryableError,
    ExposedHogQLError,
    InternalHogQLError,
)


def _all_queries_failed_notice(total_steps: int) -> str:
    noun = "the query" if total_steps == 1 else f"all {total_steps} queries"
    return (
        f"> ⚠️ This report could not be generated — {noun} the assistant wrote failed to run. "
        "Use the Manage subscription link to review the generated queries and the errors they hit.\n\n"
    )


def _safe_error_message(exc: BaseException) -> Optional[str]:
    # HogQL/ClickHouse error text can echo team-scoped identifiers, so only the query-structure error
    # classes (which describe the field/property the planner referenced) are safe to surface to the
    # subscription owner — the same trust boundary the HogQL repair loop uses when forwarding to the
    # fixer. Everything else stays type-only. Executors often wrap a resolution/exposed error in a
    # generic Exception, so walk the __cause__/__context__ chain and surface the wrapped safe message.
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, (ExposedHogQLError, ResolutionError)):
            return str(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


class ReportStage(StrEnum):
    PLANNER = "planner"
    QUERY = "query"
    SYNTHESIS = "synthesis"


class AiReportStageError(Exception):
    # PromptRejectedError is intentionally not wrapped — callers catch it by type.
    def __init__(self, stage: ReportStage, original: BaseException) -> None:
        self.stage = stage
        self.original = original
        super().__init__(f"AI report failed at {stage} stage: {original}")


@dataclass(frozen=True)
class QueryStepDiagnostic:
    # Per-step audit record persisted to the delivery's content_snapshot. The generated HogQL and the
    # failure type are otherwise discarded once the report renders, leaving a "could not be computed"
    # line with no way to see which query ran or why it failed.
    description: str
    hogql: str
    ok: bool
    error_type: Optional[str]
    # Human-readable failure reason, populated only for the query-structure error classes whose messages
    # are safe to surface (see _safe_error_message). None on success and for internal errors (type-only).
    human_readable_error: Optional[str] = None


@dataclass(frozen=True)
class AiReportResult:
    markdown: str
    diagnostics: tuple[QueryStepDiagnostic, ...]


async def generate_ai_report(
    *,
    team: Team,
    user: Optional[User],
    prompt: Optional[str],
    window_days: int,
    trace_correlation_id: Optional[Union[int, str]] = None,
) -> AiReportResult:
    if user is None:
        raise PromptRejectedError("AI report must have a user to run.")

    with slo_operation(
        spec=SloSpec(
            distinct_id=str(user.distinct_id),
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.AI_SUBSCRIPTION_PROMPT_GENERATION,
            team_id=team.id,
            resource_id=str(trace_correlation_id) if trace_correlation_id is not None else None,
        ),
        properties={"window_days": window_days},
    ) as slo:
        try:
            spec = await _plan(
                team=team, user=user, prompt=prompt, window_days=window_days, trace_id=trace_correlation_id
            )
            rendered_results, failed_count, diagnostics = await _execute_plan(spec, team, user, trace_correlation_id)
            report = await _synthesize(spec, rendered_results, team, user, trace_correlation_id)
        except PromptRejectedError:
            # A rejected prompt is the input guard doing its job, not a service failure — keep it out of
            # the error budget so user-supplied bad input doesn't burn the SLO.
            slo.succeed(rejected=True)
            raise

        total_steps = len(spec.plan.steps)
        # A degraded report (a step failed but synthesis still shipped) is an SLO success, tagged so the
        # coverage signal survives. A raised stage error is recorded as a failure by slo_operation itself.
        slo.tag(
            total_steps=total_steps,
            failed_steps=failed_count,
            query_coverage=(total_steps - failed_count) / total_steps if total_steps else 0.0,
            degraded=bool(failed_count),
        )
        if failed_count:
            logger.warning(
                "ai_report.delivered_degraded",
                trace_correlation_id=trace_correlation_id,
                failed_steps=failed_count,
                total_steps=total_steps,
            )
        if total_steps and failed_count == total_steps:
            # Every query failed, so the body is all "could not be computed" placeholders. Lead with a
            # deterministic notice (not left to the synthesis LLM) so the recipient gets a clear signal
            # instead of a confident-looking but empty report.
            report = _all_queries_failed_notice(total_steps) + report
        return AiReportResult(markdown=report, diagnostics=tuple(diagnostics))


async def _plan(
    *, team: Team, user: User, prompt: Optional[str], window_days: int, trace_id: Optional[Union[int, str]]
) -> EnrichedPromptSpec:
    try:
        return await database_sync_to_async(build_enriched_prompt, thread_sensitive=False)(
            team=team,
            user=user,
            prompt=prompt,
            window_days=window_days,
            trace_correlation_id=trace_id,
        )
    except PromptRejectedError:
        raise
    except Exception as exc:
        raise AiReportStageError(ReportStage.PLANNER, exc) from exc


async def _execute_plan(
    spec: EnrichedPromptSpec,
    team: Team,
    user: User,
    trace_correlation_id: Optional[Union[int, str]],
) -> tuple[list[str], int, list[QueryStepDiagnostic]]:
    try:
        return await _run_steps(spec, team, user, trace_correlation_id)
    except Exception as exc:
        # per-step failures degrade to placeholders in run_step; this catches orchestration failure
        raise AiReportStageError(ReportStage.QUERY, exc) from exc


async def _synthesize(
    spec: EnrichedPromptSpec,
    rendered_results: list[str],
    team: Team,
    user: User,
    trace_correlation_id: Optional[Union[int, str]],
) -> str:
    posthog_properties: dict[str, Union[str, int]] = {
        "feature": "ai_subscription",
        "stage": "synthesis",
        "trace_id": str(uuid.uuid4()),
    }
    if trace_correlation_id is not None:
        posthog_properties["subscription_id"] = trace_correlation_id

    chat = MaxChatOpenAI(
        model=DEFAULT_SYNTHESIS_MODEL,
        timeout=_SYNTHESIS_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        billable=True,
        posthog_properties=posthog_properties,
    )
    synthesis_prompt = await database_sync_to_async(resolve_prompt, thread_sensitive=False)(
        team, SYNTHESIS_PROMPT_NAME, AI_SUBSCRIPTION_SYNTHESIS_PROMPT
    )
    # Inject the failure marker from the same constant the placeholder renders, so the prompt's
    # "treat this as an error, not 'no data'" instruction can't drift from what _run_steps emits.
    synthesis_prompt = render_prompt(synthesis_prompt, {"failure_marker": QUERY_FAILED_PREFIX})

    try:
        # database_sync_to_async (not to_thread): MaxChatOpenAI reads billing/quota from the ORM
        result = await database_sync_to_async(chat.invoke, thread_sensitive=False)(
            [
                ("system", synthesis_prompt),
                ("human", _compose_synthesis_human_message(spec, rendered_results)),
            ],
        )
    except Exception as exc:
        raise AiReportStageError(ReportStage.SYNTHESIS, exc) from exc
    content = result.content if hasattr(result, "content") else str(result)
    return content if isinstance(content, str) else str(content)


def _compose_synthesis_human_message(spec: EnrichedPromptSpec, rendered_results: list[str]) -> str:
    results_block = "\n".join(rendered_results) if rendered_results else "_No query results were available._"
    # planner output from user-controlled context — strip framing markers so it can't inject
    safe_intent = strip_llm_framing_markers(spec.plan.overall_intent, max_len=500)
    return (
        f"<user_prompt>\n{spec.cleaned_prompt}\n</user_prompt>\n\n"
        f"<project_context>\n{spec.context_blob}\n</project_context>\n\n"
        f"<plan_intent>\n{safe_intent}\n</plan_intent>\n\n"
        f"<query_results>\n{results_block}\n</query_results>"
    )


async def _run_steps(
    spec: EnrichedPromptSpec,
    team: Team,
    user: User,
    trace_correlation_id: Optional[Union[int, str]],
) -> tuple[list[str], int, list[QueryStepDiagnostic]]:
    executor = AssistantQueryExecutor(team, datetime.now(tz=UTC), user=user)
    # Cap simultaneous ClickHouse scans per report; excess steps queue until a slot frees.
    step_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_STEPS)

    # Scale each step's result cap so the combined results stay within the synthesis budget even at the
    # max plan size; a small plan still gets the full per-step backstop.
    per_step_cap = min(
        _QUERY_RESULT_MAX_CHARS,
        max(_MIN_STEP_RESULT_CHARS, _SYNTHESIS_RESULTS_CHAR_BUDGET // len(spec.plan.steps)),
    )

    async def run_step(step: QueryPlanStep) -> tuple[str, QueryStepDiagnostic]:
        current_hogql = step.hogql
        last_exc: Optional[BaseException] = None
        # planner output — strip framing markers so it can't break the <query_results> envelope
        safe_description = strip_llm_framing_markers(step.description, max_len=500)

        for attempt in range(_MAX_QUERY_FIX_RETRIES + 1):
            try:
                query = AssistantHogQLQuery(query=current_hogql)
                formatted, _ = await asyncio.wait_for(
                    executor.arun_and_format_query(query),
                    timeout=_HOGQL_STEP_TIMEOUT_SECONDS,
                )
                # result values are attacker-influenceable (public project tokens) — strip framing markers
                safe_formatted = strip_llm_framing_markers(formatted, per_step_cap)
                return (
                    f"### {safe_description}\n\n{safe_formatted}",
                    QueryStepDiagnostic(description=safe_description, hogql=current_hogql, ok=True, error_type=None),
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= _MAX_QUERY_FIX_RETRIES or not isinstance(exc, _RETRYABLE_QUERY_ERRORS):
                    break
                logger.info(
                    "ai_report.query_fix_attempt",
                    trace_correlation_id=trace_correlation_id,
                    step_description=safe_description,
                    attempt=attempt + 1,
                    max_retries=_MAX_QUERY_FIX_RETRIES,
                    error_type=type(exc).__name__,
                )
                fixed = await _arequest_hogql_fix(
                    original_hogql=current_hogql,
                    # Forward the safe message (exposed/resolution errors describe the field/property the
                    # planner referenced, which is what the fixer needs); fall back to the type name.
                    error_message=_safe_error_message(exc) or type(exc).__name__,
                    step_description=safe_description,
                    team=team,
                    user=user,
                    trace_correlation_id=trace_correlation_id,
                )
                if not fixed or fixed.strip() == current_hogql.strip():
                    break
                current_hogql = fixed

        logger.warning(
            "ai_report.query_failed",
            trace_correlation_id=trace_correlation_id,
            step_description=safe_description,
            exc_info=last_exc,
        )
        if last_exc is not None:
            capture_exception(last_exc, {"trace_correlation_id": trace_correlation_id, "stage": "query"})
        # type only — ClickHouse errors can echo team-scoped identifiers
        type_name = type(last_exc).__name__ if last_exc is not None else "UnknownError"
        # Explicit failure marker, distinct from a genuinely-empty result, so synthesis reports the
        # metric as "could not be computed" instead of paraphrasing the failure into "no data".
        return (
            f"### {safe_description}\n\n_{QUERY_FAILED_PREFIX} ({type_name}) — metric not computed, not empty data._",
            QueryStepDiagnostic(
                description=safe_description,
                hogql=current_hogql,
                ok=False,
                error_type=type_name,
                human_readable_error=_safe_error_message(last_exc) if last_exc is not None else None,
            ),
        )

    async def run_step_bounded(step: QueryPlanStep) -> tuple[str, QueryStepDiagnostic]:
        # Hold a slot for the whole step (query + any fix/rerun) so concurrent ClickHouse load stays bounded.
        async with step_semaphore:
            return await run_step(step)

    step_results = await asyncio.gather(*(run_step_bounded(step) for step in spec.plan.steps))
    rendered = [text for text, _ in step_results]
    diagnostics = [diag for _, diag in step_results]
    failed_count = sum(1 for diag in diagnostics if not diag.ok)
    return rendered, failed_count, diagnostics


async def _arequest_hogql_fix(
    *,
    original_hogql: str,
    error_message: str,
    step_description: str,
    team: Team,
    user: User,
    trace_correlation_id: Optional[Union[int, str]],
) -> Optional[str]:
    posthog_properties: dict[str, Union[str, int]] = {"feature": "ai_subscription", "stage": "query_fix"}
    if trace_correlation_id is not None:
        posthog_properties["subscription_id"] = trace_correlation_id

    llm = MaxChatOpenAI(
        model=DEFAULT_PLANNER_MODEL,
        timeout=_FIX_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        billable=True,
        posthog_properties=posthog_properties,
    ).with_structured_output(HogQLFix, method="json_schema", include_raw=False)

    fix_prompt = await database_sync_to_async(resolve_prompt, thread_sensitive=False)(
        team, HOGQL_FIX_PROMPT_NAME, HOGQL_FIX_PROMPT
    )
    rendered = render_prompt(
        fix_prompt,
        {"description": step_description, "error": error_message, "original_hogql": original_hogql},
    )

    try:
        result = await database_sync_to_async(llm.invoke, thread_sensitive=False)([("system", rendered)])
    except Exception as exc:
        logger.warning(
            "ai_report.query_fix_llm_failed",
            trace_correlation_id=trace_correlation_id,
            step_description=step_description,
            error_type=type(exc).__name__,
        )
        return None

    if not isinstance(result, HogQLFix):
        return None
    fixed = result.fixed_hogql.strip()
    return fixed or None


__all__ = ["generate_ai_report", "AiReportResult", "QueryStepDiagnostic", "AiReportStageError", "ReportStage"]
