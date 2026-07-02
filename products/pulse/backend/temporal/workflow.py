import json
import datetime as dt

import temporalio.common
import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.pulse.backend.temporal.activities import (
    GenerateBriefWorkflowInputs,
    SynthesizeActivityInputs,
    gather_brief_inputs_activity,
    synthesize_brief_activity,
)


@temporalio.workflow.defn(name="pulse-generate-brief")
class GenerateProductBriefWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> GenerateBriefWorkflowInputs:
        loaded = json.loads(inputs[0])
        return GenerateBriefWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: GenerateBriefWorkflowInputs) -> str:
        items: list[dict] = await temporalio.workflow.execute_activity(
            gather_brief_inputs_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
        return await temporalio.workflow.execute_activity(
            synthesize_brief_activity,
            SynthesizeActivityInputs(
                team_id=inputs.team_id,
                brief_id=inputs.brief_id,
                brief_config_id=inputs.brief_config_id,
                period_days=inputs.period_days,
                items=items,
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            # A failed synthesis is not retried: retrying double-spends LLM calls.
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
        )
