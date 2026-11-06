"""Compatibility definitions for per-evaluation signal Temporal histories.

New evaluation workflows skip this path. Keep the workflow and activity registered until histories
that recorded either legacy signal command have drained.
"""

import json
from dataclasses import dataclass
from datetime import timedelta

import temporalio
import posthoganalytics
import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.scoped import scoped_temporal


@dataclass
class EmitEvalSignalInputs:
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


@temporalio.activity.defn
@scoped_temporal()
async def emit_eval_signal_activity(_: EmitEvalSignalInputs) -> None:
    return


@temporalio.workflow.defn(name="emit-eval-signal")
class EmitEvalSignalWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitEvalSignalInputs:
        loaded = json.loads(inputs[0])
        return EmitEvalSignalInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: EmitEvalSignalInputs) -> None:
        with posthoganalytics.new_context(capture_exceptions=False):
            posthoganalytics.tag("team_id", inputs.team_id)
            posthoganalytics.tag("product", "signals")
            await temporalio.workflow.execute_activity(
                emit_eval_signal_activity,
                inputs,
                schedule_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
