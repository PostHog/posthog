from datetime import timedelta

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.messaging.backend.temporal.activities import (
        finish_provider_import_run_activity,
        run_provider_import_step_activity,
    )
    from products.messaging.backend.temporal.inputs import (
        ProviderImportRunInputs,
        ProviderImportStepInputs,
        ProviderImportWorkflowInputs,
    )

# A step pages through a whole provider list, which can run for hours. The heartbeat timeout finds a dead worker
# quickly, and the step continues from its last saved page on the next attempt.
STEP_TIMEOUT = timedelta(hours=6)
STEP_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
STEP_RETRY_POLICY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    non_retryable_error_types=[
        "ImportCredentialsMissing",
        "ImportCredentialsInvalid",
        "ImportRunClosed",
        "StaleImportAttempt",
        "UnknownImportStep",
        "UnknownImportProvider",
    ],
)
FINISH_RETRY_POLICY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))


@workflow.defn(name="messaging-provider-import")
class ProviderImportWorkflow(PostHogWorkflow):
    inputs_cls = ProviderImportWorkflowInputs

    @workflow.run
    async def run(self, inputs: ProviderImportWorkflowInputs) -> None:
        for step in inputs.steps:
            try:
                await workflow.execute_activity(
                    run_provider_import_step_activity,
                    ProviderImportStepInputs(team_id=inputs.team_id, run_id=inputs.run_id, step=step),
                    start_to_close_timeout=STEP_TIMEOUT,
                    heartbeat_timeout=STEP_HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY_POLICY,
                )
            except ActivityError:
                # The steps import independent data, so one failed step does not stop the others.
                workflow.logger.warning("Provider import step failed", extra={"run_id": inputs.run_id, "step": step})

        await workflow.execute_activity(
            finish_provider_import_run_activity,
            ProviderImportRunInputs(team_id=inputs.team_id, run_id=inputs.run_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=FINISH_RETRY_POLICY,
        )
