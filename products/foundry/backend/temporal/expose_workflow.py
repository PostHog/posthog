"""The foundry-expose-bet workflow: an automatic, guardrail-checked flag rollout ramp.

Started from ``logic/exposure.py``'s ``maybe_schedule_exposure`` hook, right after a
manual ``exposure.started`` event drives GATED->EXPOSED (mirrors ``gate.py``'s
``maybe_schedule_gate`` hook shape) — never from funding directly. A human/orchestrator
always sends that first ``exposure.started`` event (grey-box unchanged); this workflow
only takes over the ramp itself when ``exposure_plan.steps`` is non-empty and
``auto_start`` is true (ADR-6 decision 2).

Per step: set the flag's overall ``rollout_percentage`` (via the feature-flags facade,
activating the flag on step 0 only), emit ``exposure.advanced``, durable-sleep
``min_hours`` (a real Temporal timer — this is exactly what they're for), then — unless
this step opts out via ``halt_on_guardrail_breach: false`` — evaluate guardrails once.
A breach sets rollout back to 0, emits ``exposure.halted``, and stops; no breach advances
to the next step. Completing every step with no halt just ends the workflow — the bet
stays exposed either way (no state transition happens here; a human recording a verdict,
informed by ``logic/scout.py``'s ``verdict.proposed``, is what concludes a bet).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .constants import RECORD_EVENT_RETRY_POLICY, RECORD_EVENT_TIMEOUT

with temporalio.workflow.unsafe.imports_passed_through():
    from .activities import RecordEventInput, record_bet_event_activity
    from .expose_activities import (
        EvaluateGuardrailsInput,
        GuardrailBreachOutput,
        SetFlagRolloutInput,
        evaluate_guardrails_activity,
        set_flag_rollout_activity,
    )

# Flag writes are cheap/idempotent (re-applying the same rollout_pct is harmless); a
# short retry policy covers a transient DB blip without stalling the ramp.
SET_FLAG_ROLLOUT_TIMEOUT = timedelta(seconds=30)
SET_FLAG_ROLLOUT_RETRY_POLICY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
# A guardrail check may run a real ClickHouse query; give it more room than a flag write.
EVALUATE_GUARDRAILS_TIMEOUT = timedelta(minutes=2)
EVALUATE_GUARDRAILS_RETRY_POLICY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))


@dataclass
class ExposureStepSpec:
    rollout_pct: float
    min_hours: float
    halt_on_guardrail_breach: bool = True


@dataclass
class FoundryExposeBetInput:
    bet_id: str
    team_id: int
    bet_slug: str
    flag_id: int
    guardrails: list[dict[str, Any]] = field(default_factory=list)
    steps: list[ExposureStepSpec] = field(default_factory=list)


async def _record(input: FoundryExposeBetInput, kind: str, payload: dict[str, Any]) -> None:
    await workflow.execute_activity(
        record_bet_event_activity,
        RecordEventInput(bet_id=input.bet_id, team_id=input.team_id, kind=kind, payload=payload),
        start_to_close_timeout=RECORD_EVENT_TIMEOUT,
        retry_policy=RECORD_EVENT_RETRY_POLICY,
    )


@workflow.defn(name="foundry-expose-bet")
class FoundryExposeBetWorkflow(PostHogWorkflow):
    inputs_cls = FoundryExposeBetInput

    @workflow.run
    async def run(self, input: FoundryExposeBetInput) -> dict[str, Any]:
        for index, step in enumerate(input.steps):
            await workflow.execute_activity(
                set_flag_rollout_activity,
                SetFlagRolloutInput(
                    team_id=input.team_id,
                    flag_id=input.flag_id,
                    rollout_pct=step.rollout_pct,
                    ensure_active=index == 0,
                ),
                start_to_close_timeout=SET_FLAG_ROLLOUT_TIMEOUT,
                retry_policy=SET_FLAG_ROLLOUT_RETRY_POLICY,
            )
            await _record(input, "exposure.advanced", {"step": index, "rollout_pct": step.rollout_pct})

            await workflow.sleep(timedelta(hours=step.min_hours))

            if step.halt_on_guardrail_breach and input.guardrails:
                breach: GuardrailBreachOutput | None = await workflow.execute_activity(
                    evaluate_guardrails_activity,
                    EvaluateGuardrailsInput(bet_id=input.bet_id, team_id=input.team_id),
                    start_to_close_timeout=EVALUATE_GUARDRAILS_TIMEOUT,
                    retry_policy=EVALUATE_GUARDRAILS_RETRY_POLICY,
                )
                if breach is not None:
                    await workflow.execute_activity(
                        set_flag_rollout_activity,
                        SetFlagRolloutInput(team_id=input.team_id, flag_id=input.flag_id, rollout_pct=0),
                        start_to_close_timeout=SET_FLAG_ROLLOUT_TIMEOUT,
                        retry_policy=SET_FLAG_ROLLOUT_RETRY_POLICY,
                    )
                    await _record(
                        input,
                        "exposure.halted",
                        {"reason": "guardrail_breach", "guardrail": breach.name, "details": breach.detail},
                    )
                    return {"outcome": "halted", "step": index}

        return {"outcome": "completed"}
