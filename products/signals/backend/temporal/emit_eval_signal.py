import json
from dataclasses import dataclass
from datetime import timedelta

import structlog
import temporalio
import posthoganalytics
import temporalio.workflow
from pydantic import BaseModel, Field
from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.temporal.llm import call_llm

logger = structlog.get_logger(__name__)


@dataclass
class EmitEvalSignalInputs:
    """Strongly typed inputs for the eval signal workflow and activity."""

    team_id: int
    evaluation_id: str
    evaluation_name: str
    evaluation_prompt: str

    event_uuid: str
    event_type: str
    trace_id: str

    reasoning: str
    model: str
    provider: str

    # `service` is the OTEL_SERVICE_NAME super-property on the source `$ai_generation`
    # event. It identifies which PostHog worker (if any) made the LLM call, which lets
    # the activity drop signals that originate from PostHog's own signals pipeline
    # before doing the summarizer LLM call. Defaults to "" so in-flight v1 workflow
    # payloads that pre-date this field still deserialize cleanly.
    service: str = ""

    # First few KB of the source `$ai_generation`'s rendered input. Used as a content
    # fingerprint to drop signals whose input is a signals-pipeline prompt — defense
    # in depth in case a future internal caller forgets to set `service` to a
    # denylisted value. Defaults to "" for backward compatibility.
    event_input_preview: str = ""


class EvalSignalSummary(BaseModel):
    title: str = Field(
        description="Short title describing what this evaluation detected (max 100 chars)", max_length=100
    )
    description: str = Field(description="4-8 sentence description of the evaluation goal and why it passed")
    significance: float = Field(ge=0.0, le=1.0)


SUMMARIZE_EVAL_SYSTEM_PROMPT = """You are a concise technical writer. Your job is to produce a short signal description from an LLM trace evaluation result.

You will be given:
- The evaluation name
- The full evaluation prompt (the criteria the judge used)
- The judge's reasoning for its verdict
- Context about the target event (event type, trace ID if available)

Produce:
1. A short title (max 100 chars) that captures what the evaluation detected. This should read as a finding, not a question.
   Good: "Hallucination detected in product recommendation flow"
   Bad: "Evaluation 'hallucination_check' passed"

2. A 4-8 sentence description that explains:
   - What the evaluation was checking for (derived from the prompt)
   - Why the judge determined the result was true
   - Any relevant context about the trace or event

3. A significance score between 0 and 1:
   - 0.0 = totally insignificant, noise, expected behavior
   - 0.1-0.3 = minor, worth noting but low priority
   - 0.4-0.6 = moderate, should be investigated when time permits
   - 0.7-0.9 = high, should be prioritized and addressed soon
   - 1.0 = critical, should be acted on immediately

Base significance on: severity of the finding, breadth of impact, and how obvious or actionable the fix is.

The output will be fed into a signal grouping and investigation system that groups related findings from different observability tools and data sources, across an entire product.
Write for an engineer who hasn't seen this specific evaluation before.
Do NOT parrot the evaluation name or say "the evaluation passed". Describe the actual finding.

Keep total output under 4000 tokens - be as concise as possible, without losing important information for the downstream investigators.

Respond with a JSON object containing "title", "description", and "significance" fields. Return ONLY valid JSON, no other text. The first token of output must be {"""


def _build_eval_signal_prompt(inputs: EmitEvalSignalInputs) -> str:
    parts = [
        f"EVALUATION NAME: {inputs.evaluation_name}",
        f"\nEVALUATION PROMPT (judge criteria):\n{inputs.evaluation_prompt}",
        f"\nJUDGE REASONING:\n{inputs.reasoning}",
        f"\nTARGET EVENT TYPE: {inputs.event_type}",
    ]
    if inputs.trace_id:
        parts.append(f"TRACE ID: {inputs.trace_id}")

    return "\n".join(parts)


# PostHog workers whose `$ai_generation` events should never feed back into the
# signal pipeline. Today these all run on VIDEO_EXPORT_TASK_QUEUE under a single
# OTEL service name (the "signals worker", named "video-export" for historical
# reasons). Listed as a set so additional internal service names can be added
# without touching the guard logic.
_INTERNAL_SIGNALS_SERVICES: frozenset[str] = frozenset(
    {
        "temporal-worker-video-export",
    }
)

# Signature substrings from the signals pipeline's own LLM prompts. If a generation's
# rendered input contains any of these, it's an internal signals-pipeline call and
# must not produce a signal — otherwise the "Unhappy User" judge (and similar judges
# scanning for friction language) feeds the inbox back into itself. Kept here so that
# adding a new internal prompt elsewhere in the codebase forces us to also extend
# this list (or, better, set `service` correctly upstream).
_INTERNAL_SIGNALS_PROMPT_SIGNATURES: tuple[str, ...] = (
    # safety_filter.SAFETY_FILTER_PROMPT
    "You are a security classifier for an automated signal processing pipeline.",
    # grouping.SPECIFICITY_CHECK_SYSTEM_PROMPT
    "You are a senior engineer reviewing whether a group of signals belongs in a single pull request.",
    # grouping.MATCHING_SYSTEM_PROMPT / QUERY_GENERATION_SYSTEM_PROMPT_TEMPLATE
    "You are a signal grouping assistant.",
    # SUMMARIZE_EVAL_SYSTEM_PROMPT (this very module)
    "You are a concise technical writer. Your job is to produce a short signal description from an LLM trace evaluation result.",
    # Distinctive user-prompt markers from grouping._build_matching_prompt and
    # _build_specificity_prompt — caught even when the system prompt isn't surfaced
    # in $ai_input by the SDK (e.g. Anthropic, where `system` is a separate field).
    "DISCOVERY STRENGTH (groups found by multiple independent queries are more likely related):",
    "NEW SIGNAL PROPOSED FOR ADDITION:",
)


def _looks_like_internal_signals_call(inputs: EmitEvalSignalInputs) -> bool:
    """Return True if this `$ai_generation` originated from PostHog's signals pipeline.

    Two checks, in order of cost:
    1. `service` matches a denylisted internal worker (cheap, exact string compare).
    2. The captured input preview contains a signals-pipeline prompt signature
       (defense in depth — catches the loop even if a future internal caller
       forgets to set `service`).
    """
    if inputs.service and inputs.service in _INTERNAL_SIGNALS_SERVICES:
        return True
    if inputs.event_input_preview:
        for signature in _INTERNAL_SIGNALS_PROMPT_SIGNATURES:
            if signature in inputs.event_input_preview:
                return True
    return False


async def summarize_eval_for_signal(inputs: EmitEvalSignalInputs) -> EvalSignalSummary:
    """Use the signals LLM to produce a signal-sized summary of an eval result."""
    user_prompt = _build_eval_signal_prompt(inputs)

    def validate(text: str) -> EvalSignalSummary:
        data = json.loads(text)
        return EvalSignalSummary.model_validate(data)

    return await call_llm(
        system_prompt=SUMMARIZE_EVAL_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        validate=validate,
        thinking=True,
    )


@temporalio.activity.defn
@scoped_temporal()
async def emit_eval_signal_activity(inputs: EmitEvalSignalInputs) -> None:
    def _is_eval_enabled() -> Team | None:
        """Check SignalSourceConfig and return Team if this eval is enabled, else None."""
        try:
            source_config = SignalSourceConfig.objects.get(
                team_id=inputs.team_id,
                source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
                source_type=SignalSourceConfig.SourceType.EVALUATION,
                enabled=True,
            )
        except SignalSourceConfig.DoesNotExist:
            return None

        enabled_ids = source_config.config.get("evaluation_ids", [])
        if inputs.evaluation_id not in enabled_ids:
            return None

        return Team.objects.get(id=inputs.team_id)

    team = await database_sync_to_async(_is_eval_enabled, thread_sensitive=False)()
    if team is None:
        return

    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return

    # Drop generations that came from PostHog's own signals pipeline before we
    # spend an LLM call summarizing them. Without this guard, judges that look
    # for friction language ("Unhappy User", etc.) flag the pipeline's own
    # prompts — which embed verbatim session-replay descriptions by design —
    # and the resulting "user frustration" signals feed back into the same
    # prompts on the next run.
    if _looks_like_internal_signals_call(inputs):
        logger.info(
            "Dropped eval signal originating from signals pipeline",
            evaluation_id=inputs.evaluation_id,
            team_id=inputs.team_id,
            service=inputs.service,
        )
        return

    # LLM call to produce a signal-quality summary from the raw eval data
    summary = await summarize_eval_for_signal(inputs)

    if summary.significance < 0.1:
        return

    from products.signals.backend.api import emit_signal

    await emit_signal(
        team=team,
        source_product="llm_analytics",
        source_type="evaluation",
        source_id=f"{inputs.evaluation_id}:{inputs.event_uuid}",
        description=summary.description,
        weight=summary.significance,
        extra={
            "evaluation_id": inputs.evaluation_id,
            "target_event_id": inputs.event_uuid,
            "target_event_type": inputs.event_type,
            "trace_id": inputs.trace_id,
            "model": inputs.model,
            "provider": inputs.provider,
        },
    )

    logger.info(
        "Emitted eval signal",
        evaluation_id=inputs.evaluation_id,
        team_id=inputs.team_id,
        signal_title=summary.title,
    )


@temporalio.workflow.defn(name="emit-eval-signal")
class EmitEvalSignalWorkflow(PostHogWorkflow):
    """
    Dedicated workflow for emitting eval signals, runs on VIDEO_EXPORT_TASK_QUEUE
    (the signals worker) instead of the evals queue. Fire-and-forget from RunEvaluationWorkflow.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitEvalSignalInputs:
        loaded = json.loads(inputs[0])
        return EmitEvalSignalInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: EmitEvalSignalInputs) -> None:
        with posthoganalytics.new_context(capture_exceptions=False):
            posthoganalytics.tag("team_id", inputs.team_id)
            posthoganalytics.tag("product", "signals")
            await self._run_impl(inputs)

    async def _run_impl(self, inputs: EmitEvalSignalInputs) -> None:
        await temporalio.workflow.execute_activity(
            emit_eval_signal_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
