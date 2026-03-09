import json
from dataclasses import dataclass
from datetime import timedelta

import structlog
import temporalio
import temporalio.workflow
from pydantic import BaseModel, Field
from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

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
        await temporalio.workflow.execute_activity(
            emit_eval_signal_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
