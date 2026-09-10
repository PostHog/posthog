import json
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.experiments.backend.temporal.enrollment_census_activities import run_experiment_enrollment_census
    from products.experiments.backend.temporal.models import (
        ENROLLMENT_CENSUS_WORKFLOW_NAME,
        ExperimentPrecomputeEnrollmentCensusInputs,
    )


@temporalio.workflow.defn(name=ENROLLMENT_CENSUS_WORKFLOW_NAME)
class ExperimentPrecomputeEnrollmentCensusWorkflow(PostHogWorkflow):
    """Report which teams would qualify for experiment precomputation enrollment.

    Report-only: candidates and exclusions are logged (one line per team, queryable in Loki);
    nothing is written. See ``enrollment_census_logic`` for the criteria.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentPrecomputeEnrollmentCensusInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return ExperimentPrecomputeEnrollmentCensusInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentPrecomputeEnrollmentCensusInputs) -> dict:
        result = await temporalio.workflow.execute_activity(
            run_experiment_enrollment_census,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        temporalio.workflow.logger.info(f"experiment precompute enrollment census finished: {result}")
        return result
