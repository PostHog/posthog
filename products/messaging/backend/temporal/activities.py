from dataclasses import asdict
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import asyncify

from products.messaging.backend.provider_imports.metrics import IMPORT_CHUNK_DURATION, IMPORT_CHUNK_RETRIES
from products.messaging.backend.provider_imports.runs import finish_run, record_people_import, run_step
from products.messaging.backend.temporal.inputs import (
    ContactChunkInputs,
    ContactChunkResult,
    ContactsCohortInputs,
    ProviderImportRunInputs,
    ProviderImportStepInputs,
    ProviderImportStepResult,
    RecordPeopleImportInputs,
)
from products.workflows.backend.facade.people_import import (
    ContactsCaptureFailed,
    discard_staged_contacts,
    fail_contacts_cohort,
    fill_contacts_cohort,
    import_contact_chunk,
)


@activity.defn(name="messaging-provider-import.run_step")
@asyncify
def run_provider_import_step_activity(inputs: ProviderImportStepInputs) -> ProviderImportStepResult | None:
    # Histories from before the step returned its contact lists hold None here.
    with HeartbeaterSync():
        plans = run_step(inputs.team_id, UUID(inputs.run_id), inputs.step, activity.info().attempt)
    return ProviderImportStepResult(people_imports=plans)


@activity.defn(name="messaging-provider-import.finish_run")
@asyncify
def finish_provider_import_run_activity(inputs: ProviderImportRunInputs) -> None:
    finish_run(inputs.team_id, UUID(inputs.run_id))


@activity.defn(name="messaging-provider-import.discard_staged_contacts")
@asyncify
def discard_staged_contacts_activity(inputs: ProviderImportRunInputs) -> None:
    discard_staged_contacts(inputs.team_id, inputs.run_id)


@activity.defn(name="messaging-provider-import.import_contact_chunk")
@asyncify
def import_contact_chunk_activity(inputs: ContactChunkInputs) -> ContactChunkResult:
    labels = {"provider": inputs.provider, "step": inputs.step}
    attempt = activity.info().attempt
    if attempt > 1:
        IMPORT_CHUNK_RETRIES.labels(**labels).inc()
    with HeartbeaterSync(), IMPORT_CHUNK_DURATION.labels(**labels).time():
        try:
            outcome = import_contact_chunk(
                inputs.team_id,
                inputs.storage_prefix,
                inputs.chunk,
                send_events=inputs.send_events,
                created_by_id=inputs.created_by_id,
                wait_for_people=inputs.wait_for_people,
            )
        except ContactsCaptureFailed as error:
            # The workflow reads the details to count the people capture did take from a part that failed.
            raise ApplicationError(
                str(error), error.acknowledged, error.new_people, type="ContactsCaptureFailed"
            ) from error
    return ContactChunkResult(
        people=outcome.people, found=outcome.found, attempt=attempt, new_people=outcome.new_people
    )


@activity.defn(name="messaging-provider-import.fill_contacts_cohort")
@asyncify
def fill_contacts_cohort_activity(inputs: ContactsCohortInputs) -> int:
    """Returns how many people left the cohort."""
    with HeartbeaterSync():
        return fill_contacts_cohort(
            inputs.team_id, inputs.cohort_id, inputs.storage_prefix, inputs.chunks, created_by_id=inputs.created_by_id
        ).removed


@activity.defn(name="messaging-provider-import.fail_contacts_cohort")
@asyncify
def fail_contacts_cohort_activity(inputs: ContactsCohortInputs) -> None:
    fail_contacts_cohort(inputs.team_id, inputs.cohort_id)


@activity.defn(name="messaging-provider-import.record_people_import")
@asyncify
def record_people_import_activity(inputs: RecordPeopleImportInputs) -> None:
    record_people_import(inputs.team_id, UUID(inputs.run_id), inputs.step, asdict(inputs.outcome))
