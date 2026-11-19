from datetime import timedelta

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.messaging.backend.temporal.activities import (
        fail_contacts_cohort_activity,
        fill_contacts_cohort_activity,
        finish_provider_import_run_activity,
        import_contact_chunk_activity,
        record_people_import_activity,
        run_provider_import_step_activity,
    )
    from products.messaging.backend.temporal.inputs import (
        ContactChunkInputs,
        ContactsCohortInputs,
        ContactsImportOutcome,
        ProviderContactsImportInputs,
        ProviderImportRunInputs,
        ProviderImportStepInputs,
        ProviderImportStepResult,
        ProviderImportWorkflowInputs,
        RecordPeopleImportInputs,
    )

# A step pages through a whole provider list, which can run for days. The heartbeat timeout finds a dead worker
# quickly, and the step continues from its last saved page on the next attempt.
STEP_TIMEOUT = timedelta(days=2)
STEP_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
STEP_RETRY_POLICY = RetryPolicy(
    # Each attempt continues from the last saved page, so a step that outlives several worker restarts still finishes.
    maximum_attempts=20,
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    non_retryable_error_types=[
        "ImportCredentialsMissing",
        "ImportCredentialsInvalid",
        "ImportTooLarge",
        "ImportAccessLost",
        "ImportStepBlocked",
        "ImportRunClosed",
        "StaleImportAttempt",
        "UnknownImportStep",
        "UnknownImportProvider",
    ],
)
FINISH_RETRY_POLICY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5))
CONTACTS_IMPORT_PATCH = "provider-contacts-import-2026-11"
# A part sends its events and then waits up to 10 minutes for ingestion to create its people.
CHUNK_TIMEOUT = timedelta(minutes=30)
CHUNK_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
CHUNK_RETRY_POLICY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)


@workflow.defn(name="messaging-provider-import")
class ProviderImportWorkflow(PostHogWorkflow):
    inputs_cls = ProviderImportWorkflowInputs

    @workflow.run
    async def run(self, inputs: ProviderImportWorkflowInputs) -> None:
        for step in inputs.steps:
            try:
                result = await workflow.execute_activity(
                    run_provider_import_step_activity,
                    ProviderImportStepInputs(team_id=inputs.team_id, run_id=inputs.run_id, step=step),
                    start_to_close_timeout=STEP_TIMEOUT,
                    heartbeat_timeout=STEP_HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY_POLICY,
                )
            except ActivityError:
                # The steps import independent data, so one failed step does not stop the others.
                workflow.logger.warning("Provider import step failed", extra={"run_id": inputs.run_id, "step": step})
                continue
            if workflow.patched(CONTACTS_IMPORT_PATCH) and result is not None and result.people_imports:
                # Later steps, such as contact properties, expect these people to exist.
                await self._import_contacts(inputs, step, result)

        await workflow.execute_activity(
            finish_provider_import_run_activity,
            ProviderImportRunInputs(team_id=inputs.team_id, run_id=inputs.run_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=FINISH_RETRY_POLICY,
        )

    async def _import_contacts(
        self, inputs: ProviderImportWorkflowInputs, step: str, result: ProviderImportStepResult
    ) -> None:
        try:
            outcome = await workflow.execute_child_workflow(
                ProviderContactsImportWorkflow.run,
                ProviderContactsImportInputs(
                    team_id=inputs.team_id, run_id=inputs.run_id, people_imports=result.people_imports
                ),
                # One per run and step, so a step that runs again can't send its contacts twice.
                id=f"{CONTACTS_IMPORT_WORKFLOW}-{inputs.run_id}-{step}",
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except ChildWorkflowError:
            workflow.logger.warning("Provider contacts import failed", extra={"run_id": inputs.run_id, "step": step})
            outcome = ContactsImportOutcome(failed_lists=len(result.people_imports))
        await workflow.execute_activity(
            record_people_import_activity,
            RecordPeopleImportInputs(team_id=inputs.team_id, run_id=inputs.run_id, step=step, outcome=outcome),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=FINISH_RETRY_POLICY,
        )


CONTACTS_IMPORT_WORKFLOW = "messaging-provider-contacts-import"


@workflow.defn(name=CONTACTS_IMPORT_WORKFLOW)
class ProviderContactsImportWorkflow(PostHogWorkflow):
    """Sends a step's stored contact lists part by part, then sets each list's cohort to exactly its people."""

    inputs_cls = ProviderContactsImportInputs

    @workflow.run
    async def run(self, inputs: ProviderContactsImportInputs) -> ContactsImportOutcome:
        people = found = removed = failed_lists = retried_chunks = 0
        for plan in inputs.people_imports:
            cohort = ContactsCohortInputs(
                team_id=inputs.team_id, cohort_id=plan.cohort_id, storage_prefix=plan.storage_prefix, chunks=plan.chunks
            )
            try:
                for chunk in range(plan.chunks):
                    sent = await workflow.execute_activity(
                        import_contact_chunk_activity,
                        ContactChunkInputs(
                            team_id=inputs.team_id,
                            storage_prefix=plan.storage_prefix,
                            chunk=chunk,
                            send_events=plan.send_events,
                        ),
                        start_to_close_timeout=CHUNK_TIMEOUT,
                        heartbeat_timeout=CHUNK_HEARTBEAT_TIMEOUT,
                        retry_policy=CHUNK_RETRY_POLICY,
                    )
                    people += sent.people
                    found += sent.found
                    retried_chunks += sent.attempt > 1
                removed += await workflow.execute_activity(
                    fill_contacts_cohort_activity,
                    cohort,
                    start_to_close_timeout=CHUNK_TIMEOUT,
                    heartbeat_timeout=CHUNK_HEARTBEAT_TIMEOUT,
                    retry_policy=CHUNK_RETRY_POLICY,
                )
            except ActivityError:
                # The lists fill separate cohorts, so one that fails does not stop the others.
                workflow.logger.warning("Contact list import failed", extra={"cohort_id": plan.cohort_id})
                failed_lists += 1
                await workflow.execute_activity(
                    fail_contacts_cohort_activity,
                    cohort,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=FINISH_RETRY_POLICY,
                )
        return ContactsImportOutcome(
            people=people, found=found, removed=removed, failed_lists=failed_lists, retried_chunks=retried_chunks
        )
