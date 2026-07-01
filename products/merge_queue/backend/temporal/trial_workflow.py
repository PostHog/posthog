"""Trial workflow — durable orchestration of one full-suite trial.

A trial spans minutes of CI and the queue loop must survive deploys, so Temporal carries it.
The workflow is intentionally thin: mark the trial running, run the full suite against the
projected state, record the verdict. The engine lifecycle (invoked by `record_trial_result`)
owns what happens next — green → merge, red → triage.
"""

import json
from dataclasses import dataclass
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.merge_queue.backend.temporal.activities import (
        RecordResultInput,
        SuiteResult,
        TrialRef,
        mark_trial_running,
        record_trial_result,
        run_full_suite,
    )


@dataclass
class TrialWorkflowInputs:
    trial_id: str


@temporalio.workflow.defn(name="merge-queue-trial")
class TrialWorkflow(PostHogWorkflow):
    inputs_cls = TrialWorkflowInputs

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TrialWorkflowInputs:
        return TrialWorkflowInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: TrialWorkflowInputs) -> bool:
        ref = TrialRef(trial_id=inputs.trial_id)

        await workflow.execute_activity(
            mark_trial_running,
            ref,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # The full suite — no test selection. Real CI dispatch is stubbed for now.
        try:
            result: SuiteResult = await workflow.execute_activity(
                run_full_suite,
                ref,
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as err:
            workflow.logger.exception("run_full_suite activity failed; recording failed verdict")
            result = SuiteResult(passed=False, failing_tests=[f"internal:{type(err).__name__}"])

        await workflow.execute_activity(
            record_trial_result,
            RecordResultInput(trial_id=inputs.trial_id, passed=result.passed, failing_tests=result.failing_tests),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return result.passed
