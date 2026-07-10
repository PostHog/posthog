import datetime as dt

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow

from products.pulse.backend.temporal.activities import (
    gather_brief_inputs_activity,
    mark_brief_failed_activity,
    mark_brief_quiet_activity,
    prepare_mission_activity,
    run_agent_activity,
    synthesize_brief_activity,
    validate_and_persist_activity,
)
from products.pulse.backend.temporal.inputs import (
    GENERATE_BRIEF_WORKFLOW_NAME,
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    RunAgentInputs,
    SynthesizeActivityInputs,
    ValidatePersistInputs,
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
            if inputs.engine == "agent":
                return await self._run_agent_engine(inputs)
            return await self._run_synthesize_engine(inputs)
        except Exception as exc:
            # Without this, a failed run strands the brief in GENERATING forever.
            await temporalio.workflow.execute_activity(
                mark_brief_failed_activity,
                MarkBriefFailedInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, error=_error_message(exc)),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
            raise

    async def _run_synthesize_engine(self, inputs: GenerateBriefWorkflowInputs) -> str:
        items: list[dict] = await temporalio.workflow.execute_activity(
            gather_brief_inputs_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
        return await temporalio.workflow.execute_activity(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, items=items),
            start_to_close_timeout=dt.timedelta(minutes=5),
            # A failed synthesis is not retried: retrying double-spends LLM calls.
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
        )

    async def _run_agent_engine(self, inputs: GenerateBriefWorkflowInputs) -> str:
        bundle: dict = await temporalio.workflow.execute_activity(
            prepare_mission_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
        if not bundle.get("seed_items") and bundle.get("mission", "general_brief") == "general_brief":
            # Quiet-week cheap path: no seeds -> no sandbox, no LLM spend. Only the general
            # brief takes it — for query_performance the archive, not the scan, is the data
            # source, so an empty seed list still warrants the agent run.
            await temporalio.workflow.execute_activity(
                mark_brief_quiet_activity,
                MarkBriefFailedInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, error=""),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
            return "quiet"
        result: dict = await temporalio.workflow.execute_activity(
            run_agent_activity,
            RunAgentInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, bundle=bundle),
            start_to_close_timeout=dt.timedelta(minutes=30),
            # One sandbox lifetime; a retry double-spends an entire agent run.
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
        )
        return await temporalio.workflow.execute_activity(
            validate_and_persist_activity,
            ValidatePersistInputs(
                team_id=inputs.team_id,
                brief_id=inputs.brief_id,
                report=result["report"],
                agent_session_ref=result["agent_session_ref"],
                transcript_key=result["transcript_key"],
                seed_items=bundle.get("seed_items", []),
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
