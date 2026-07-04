import datetime as dt

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow

from products.pulse.backend.temporal.activities import (
    gather_brief_inputs_activity,
    mark_brief_failed_activity,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.inputs import (
    GENERATE_BRIEF_WORKFLOW_NAME,
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    SynthesizeActivityInputs,
)


def _error_message(exc: Exception) -> str:
    # ActivityError's own message is a generic wrapper; the cause carries the real failure.
    if isinstance(exc, temporalio.exceptions.ActivityError) and exc.cause is not None:
        return str(exc.cause)
    return str(exc)


@temporalio.workflow.defn(name=GENERATE_BRIEF_WORKFLOW_NAME)
class GenerateProductBriefWorkflow(PostHogWorkflow):
    inputs_cls = GenerateBriefWorkflowInputs

    @temporalio.workflow.run
    async def run(self, inputs: GenerateBriefWorkflowInputs) -> str:
        try:
            items: list[dict] = await temporalio.workflow.execute_activity(
                gather_brief_inputs_activity,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
            )
            return await temporalio.workflow.execute_activity(
                synthesize_brief_activity,
                SynthesizeActivityInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, items=items),
                # Sized to the activity's worst case: collectors (accountability's attempt
                # budget) + the investigate stage (60s planner + 180s stage deadline + up to
                # ~90s for the step in flight at the deadline) + synthesis (2 x 120s). An
                # activity timeout here fails the brief (maximum_attempts=1), so the budget
                # must cover the stage deadlines rather than race them.
                start_to_close_timeout=dt.timedelta(minutes=10),
                # A failed synthesis is not retried: retrying double-spends LLM calls.
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            # Without this, a failed run strands the brief in GENERATING forever.
            await temporalio.workflow.execute_activity(
                mark_brief_failed_activity,
                MarkBriefFailedInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, error=_error_message(exc)),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
            raise
