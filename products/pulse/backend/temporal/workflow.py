import datetime as dt

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow

from products.pulse.backend.temporal.activities import (
    REPLAY_PATTERNS_ACTIVITY_TIMEOUT_MINUTES,
    gather_brief_inputs_activity,
    investigate_replay_patterns_activity,
    mark_brief_failed_activity,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.inputs import (
    GENERATE_BRIEF_WORKFLOW_NAME,
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    ReplayPatternsActivityInputs,
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
            replay_findings: list[dict] = []
            try:
                replay_findings = await temporalio.workflow.execute_activity(
                    investigate_replay_patterns_activity,
                    ReplayPatternsActivityInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, items=items),
                    start_to_close_timeout=dt.timedelta(minutes=REPLAY_PATTERNS_ACTIVITY_TIMEOUT_MINUTES),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                )
            except Exception:
                # Best-effort: a slow or failed replay analysis must never fail the brief — it
                # ships without the replay findings rather than landing in FAILED.
                temporalio.workflow.logger.warning("pulse_replay_activity_degraded", exc_info=True)
            return await temporalio.workflow.execute_activity(
                synthesize_brief_activity,
                SynthesizeActivityInputs(
                    team_id=inputs.team_id, brief_id=inputs.brief_id, items=items, replay_findings=replay_findings
                ),
                # The ceiling must exceed the internal budgets (collectors, planner, the
                # investigation stage deadline, synthesis retries): an activity timeout here
                # fails the brief (maximum_attempts=1). The true margin depends on collector
                # latency, so the ceiling is stated simply rather than itemized.
                start_to_close_timeout=dt.timedelta(minutes=15),
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
