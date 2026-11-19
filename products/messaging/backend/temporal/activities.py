from dataclasses import asdict
from uuid import UUID

from temporalio import activity

from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import asyncify

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


@activity.defn(name="messaging-provider-import.import_contact_chunk")
@asyncify
def import_contact_chunk_activity(inputs: ContactChunkInputs) -> ContactChunkResult:
    with HeartbeaterSync():
        outcome = import_contact_chunk(
            inputs.team_id, inputs.storage_prefix, inputs.chunk, send_events=inputs.send_events
        )
    return ContactChunkResult(people=outcome.people, found=outcome.found, attempt=activity.info().attempt)


@activity.defn(name="messaging-provider-import.fill_contacts_cohort")
@asyncify
def fill_contacts_cohort_activity(inputs: ContactsCohortInputs) -> int:
    """Returns how many people left the cohort."""
    with HeartbeaterSync():
        return fill_contacts_cohort(inputs.team_id, inputs.cohort_id, inputs.storage_prefix, inputs.chunks).removed


@activity.defn(name="messaging-provider-import.fail_contacts_cohort")
@asyncify
def fail_contacts_cohort_activity(inputs: ContactsCohortInputs) -> None:
    fail_contacts_cohort(inputs.team_id, inputs.cohort_id)


@activity.defn(name="messaging-provider-import.record_people_import")
@asyncify
def record_people_import_activity(inputs: RecordPeopleImportInputs) -> None:
    record_people_import(inputs.team_id, UUID(inputs.run_id), inputs.step, asdict(inputs.outcome))
