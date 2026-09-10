import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow

from products.pulse.backend.config import (
    GATHER_ACTIVITY_TIMEOUT,
    GATHER_MAX_ATTEMPTS,
    MARK_FAILED_ACTIVITY_TIMEOUT,
    MARK_FAILED_MAX_ATTEMPTS,
    SYNTHESIZE_ACTIVITY_TIMEOUT,
    SYNTHESIZE_MAX_ATTEMPTS,
)
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
                start_to_close_timeout=GATHER_ACTIVITY_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=GATHER_MAX_ATTEMPTS),
            )
            return await temporalio.workflow.execute_activity(
                synthesize_brief_activity,
                SynthesizeActivityInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, items=items),
                start_to_close_timeout=SYNTHESIZE_ACTIVITY_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=SYNTHESIZE_MAX_ATTEMPTS),
            )
        except Exception as exc:
            # Without this, a failed run strands the brief in GENERATING forever.
            await temporalio.workflow.execute_activity(
                mark_brief_failed_activity,
                MarkBriefFailedInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, error=_error_message(exc)),
                start_to_close_timeout=MARK_FAILED_ACTIVITY_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=MARK_FAILED_MAX_ATTEMPTS),
            )
            raise
