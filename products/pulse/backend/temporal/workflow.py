from typing import cast

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow

from products.pulse.backend.temporal.activities import (
    expand_mission_activity,
    gather_brief_inputs_activity,
    mark_brief_failed_activity,
    mark_brief_quiet_activity,
    prepare_mission_activity,
    run_agent_activity,
    synthesize_brief_activity,
    validate_and_persist_activity,
)
from products.pulse.backend.temporal.inputs import (
    EXPAND_MISSION_ATTEMPTS,
    EXPAND_MISSION_TIMEOUT,
    GATHER_BRIEF_ATTEMPTS,
    GATHER_BRIEF_TIMEOUT,
    GENERATE_BRIEF_WORKFLOW_NAME,
    MARK_STATUS_ATTEMPTS,
    MARK_STATUS_TIMEOUT,
    MISSION_GOAL_STATUS_KEY,
    MISSION_SEED_ITEMS_KEY,
    PREPARE_MISSION_ATTEMPTS,
    PREPARE_MISSION_TIMEOUT,
    QUIET_BRIEF_STATUS,
    RUN_AGENT_ATTEMPTS,
    RUN_AGENT_TIMEOUT,
    SYNTHESIZE_ATTEMPTS,
    SYNTHESIZE_TIMEOUT,
    VALIDATE_PERSIST_ATTEMPTS,
    VALIDATE_PERSIST_TIMEOUT,
    ExpandMissionInputs,
    GenerateBriefWorkflowInputs,
    MarkBriefFailedInputs,
    MarkBriefQuietInputs,
    MissionBundleDict,
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
                start_to_close_timeout=MARK_STATUS_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=MARK_STATUS_ATTEMPTS),
            )
            raise

    async def _run_synthesize_engine(self, inputs: GenerateBriefWorkflowInputs) -> str:
        items: list[dict] = await temporalio.workflow.execute_activity(
            gather_brief_inputs_activity,
            inputs,
            start_to_close_timeout=GATHER_BRIEF_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=GATHER_BRIEF_ATTEMPTS),
        )
        return await temporalio.workflow.execute_activity(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, items=items),
            start_to_close_timeout=SYNTHESIZE_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=SYNTHESIZE_ATTEMPTS),
        )

    async def _run_agent_engine(self, inputs: GenerateBriefWorkflowInputs) -> str:
        # prepare returns the full serialized bundle; narrow to the keys this workflow reads.
        bundle = cast(
            MissionBundleDict,
            await temporalio.workflow.execute_activity(
                prepare_mission_activity,
                inputs,
                start_to_close_timeout=PREPARE_MISSION_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=PREPARE_MISSION_ATTEMPTS),
            ),
        )
        if not bundle.get(MISSION_SEED_ITEMS_KEY):
            # Quiet-week cheap path: no seeds -> no sandbox, no LLM spend.
            await temporalio.workflow.execute_activity(
                mark_brief_quiet_activity,
                MarkBriefQuietInputs(
                    team_id=inputs.team_id,
                    brief_id=inputs.brief_id,
                    reason=f"No significant activity in the last {inputs.period_days} days, so there's nothing to report yet.",
                ),
                start_to_close_timeout=MARK_STATUS_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=MARK_STATUS_ATTEMPTS),
            )
            return QUIET_BRIEF_STATUS
        if inputs.expand:
            # Enrichment is best-effort: if the activity fails or times out, fall back to the
            # prepared bundle rather than failing a brief prepare_mission already produced.
            try:
                bundle = cast(
                    MissionBundleDict,
                    await temporalio.workflow.execute_activity(
                        expand_mission_activity,
                        ExpandMissionInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, bundle=bundle),
                        start_to_close_timeout=EXPAND_MISSION_TIMEOUT,
                        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=EXPAND_MISSION_ATTEMPTS),
                    ),
                )
            except temporalio.exceptions.ActivityError:
                temporalio.workflow.logger.warning("pulse_expand_activity_failed, proceeding un-enriched")
        result: dict = await temporalio.workflow.execute_activity(
            run_agent_activity,
            RunAgentInputs(team_id=inputs.team_id, brief_id=inputs.brief_id, bundle=bundle),
            start_to_close_timeout=RUN_AGENT_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=RUN_AGENT_ATTEMPTS),
        )
        return await temporalio.workflow.execute_activity(
            validate_and_persist_activity,
            ValidatePersistInputs(
                team_id=inputs.team_id,
                brief_id=inputs.brief_id,
                report=result["report"],
                agent_session_ref=result["agent_session_ref"],
                transcript_key=result["transcript_key"],
                seed_items=bundle.get(MISSION_SEED_ITEMS_KEY, []),
                has_goal=bundle.get(MISSION_GOAL_STATUS_KEY) is not None,
            ),
            start_to_close_timeout=VALIDATE_PERSIST_TIMEOUT,
            # persist is fingerprint-idempotent, so the retry (unlike synthesize) is safe: a
            # post-commit crash-retry re-emits no signals and at worst double-counts one
            # product_brief_generated event (count=0) — accepted.
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=VALIDATE_PERSIST_ATTEMPTS),
        )
