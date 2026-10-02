"""Run one experiment synthesis: propose themes, assign summaries to them, then write digests and differences."""

import datetime as dt

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import unwrap_temporal_cause

from products.replay_vision.backend.temporal.activities.experiment_synthesis import (
    assign_synthesis_themes_activity,
    fail_experiment_synthesis_activity,
    propose_synthesis_themes_activity,
    write_synthesis_differences_activity,
    write_synthesis_digests_activity,
)
from products.replay_vision.backend.temporal.constants import (
    EXPERIMENT_SYNTHESIS_STEP_TIMEOUT,
    EXPERIMENT_SYNTHESIS_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.synthesis_types import (
    ExperimentSynthesisInputs,
    FailExperimentSynthesisInputs,
)

# A step's model call or embedding read can fail transiently; a SynthesisError is raised non-retryable.
_STEP_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(seconds=60),
    maximum_attempts=3,
)
_STATE_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=5,
)
_STEPS = (
    propose_synthesis_themes_activity,
    assign_synthesis_themes_activity,
    write_synthesis_digests_activity,
    write_synthesis_differences_activity,
)


def _cause_message(e: BaseException) -> str:
    cause = unwrap_temporal_cause(e) or e
    return str(getattr(cause, "message", None) or cause or type(cause).__name__)[:500]


@wf.defn(name=EXPERIMENT_SYNTHESIS_WORKFLOW_NAME)
class ExperimentSynthesisWorkflow(PostHogWorkflow):
    """Each step reads and writes the synthesis row, so the workflow carries only its id."""

    inputs_cls = ExperimentSynthesisInputs

    @wf.run
    async def run(self, inputs: ExperimentSynthesisInputs) -> None:
        try:
            for step in _STEPS:
                await wf.execute_activity(
                    step,
                    inputs,
                    start_to_close_timeout=EXPERIMENT_SYNTHESIS_STEP_TIMEOUT,
                    retry_policy=_STEP_RETRY,
                )
        except Exception as e:
            # The row is what the readout shows, so it must not stay `running` after a failure.
            await wf.execute_activity(
                fail_experiment_synthesis_activity,
                FailExperimentSynthesisInputs(
                    synthesis_id=inputs.synthesis_id, team_id=inputs.team_id, error=_cause_message(e)
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_STATE_RETRY,
            )
            raise
