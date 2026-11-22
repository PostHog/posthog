import uuid
import asyncio
import logging
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.messaging.backend.provider_imports.base import PeopleImportPlan
from products.messaging.backend.temporal.inputs import (
    ContactChunkInputs,
    ContactChunkResult,
    ContactsCohortInputs,
    ContactsImportOutcome,
    ProviderImportRunInputs,
    ProviderImportStepInputs,
    ProviderImportStepResult,
    ProviderImportWorkflowInputs,
    RecordPeopleImportInputs,
)
from products.messaging.backend.temporal.workflow import ProviderContactsImportWorkflow, ProviderImportWorkflow


@pytest.mark.asyncio
async def test_a_failed_step_does_not_stop_later_steps_or_the_finish(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    attempted_steps: list[str] = []
    finished_runs: list[str] = []

    @activity.defn(name="messaging-provider-import.run_step")
    async def run_step(inputs: ProviderImportStepInputs) -> None:
        attempted_steps.append(inputs.step)
        if inputs.step == "categories":
            raise ApplicationError("The key was deleted", type="ImportCredentialsMissing")

    @activity.defn(name="messaging-provider-import.finish_run")
    async def finish_run(inputs: ProviderImportRunInputs) -> None:
        finished_runs.append(inputs.run_id)

    @activity.defn(name="messaging-provider-import.discard_staged_contacts")
    async def discard(inputs: ProviderImportRunInputs) -> None:
        pass

    run_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="provider-import-test",
            workflows=[ProviderImportWorkflow],
            activities=[run_step, finish_run, discard],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ProviderImportWorkflow.run,
                ProviderImportWorkflowInputs(team_id=1, run_id=run_id, steps=["categories", "suppressions"]),
                id=f"provider-import-test-{run_id}",
                task_queue="provider-import-test",
                execution_timeout=timedelta(minutes=5),
            )

    assert attempted_steps == ["categories", "suppressions"]
    assert finished_runs == [run_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled"])
async def test_the_run_deletes_its_stored_contacts_however_it_ends(ending: str) -> None:
    run_id = str(uuid.uuid4())
    stored: dict[str, str] = {}
    step_started = asyncio.Event()

    @activity.defn(name="messaging-provider-import.run_step")
    async def run_step(inputs: ProviderImportStepInputs) -> ProviderImportStepResult:
        stored[f"{inputs.run_id}/{inputs.step}"] = "[]"
        step_started.set()
        if ending == "cancelled":
            await asyncio.Event().wait()
        return ProviderImportStepResult(people_imports=[])

    @activity.defn(name="messaging-provider-import.finish_run")
    async def finish_run(inputs: ProviderImportRunInputs) -> None:
        if ending == "failed":
            raise ApplicationError("The database went away", non_retryable=True)

    @activity.defn(name="messaging-provider-import.discard_staged_contacts")
    async def discard(inputs: ProviderImportRunInputs) -> None:
        for key in [key for key in stored if key.startswith(f"{inputs.run_id}/")]:
            del stored[key]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="provider-import-test",
            workflows=[ProviderImportWorkflow],
            activities=[run_step, finish_run, discard],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                ProviderImportWorkflow.run,
                ProviderImportWorkflowInputs(team_id=1, run_id=run_id, steps=["contacts"]),
                id=f"provider-import-test-{run_id}",
                task_queue="provider-import-test",
                execution_timeout=timedelta(minutes=5),
            )
            if ending == "cancelled":
                await step_started.wait()
                await handle.cancel()
            if ending == "completed":
                await handle.result()
            else:
                with pytest.raises(WorkflowFailureError):
                    await handle.result()

    assert step_started.is_set()
    assert stored == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "fill", "send", "partial send"])
async def test_stored_contacts_are_sent_part_by_part_before_the_next_step(failure: str | None) -> None:
    calls: list[str] = []
    recorded: list[ContactsImportOutcome] = []
    chunk_attempts: dict[tuple[str, int], int] = {}
    plan = PeopleImportPlan(cohort_id=7, storage_prefix="prefix", chunks=2, send_events=True)
    segment = PeopleImportPlan(cohort_id=8, storage_prefix="segment", chunks=1, send_events=False)

    @activity.defn(name="messaging-provider-import.run_step")
    async def run_step(inputs: ProviderImportStepInputs) -> ProviderImportStepResult:
        calls.append(inputs.step)
        return ProviderImportStepResult(people_imports=[plan, segment] if inputs.step == "contacts" else [])

    @activity.defn(name="messaging-provider-import.import_contact_chunk")
    async def import_chunk(inputs: ContactChunkInputs) -> ContactChunkResult:
        key = (inputs.storage_prefix, inputs.chunk)
        chunk_attempts[key] = chunk_attempts.get(key, 0) + 1
        if failure == "send" and key == ("prefix", 1):
            raise ApplicationError("Capture didn't acknowledge 3 events.")
        if failure == "partial send" and key == ("prefix", 1):
            raise ApplicationError("Capture didn't acknowledge 1 events.", 2, 1, type="ContactsCaptureFailed")
        if key == ("prefix", 1) and chunk_attempts[key] == 1:
            raise ApplicationError("The worker went away")
        calls.append(
            f"{inputs.storage_prefix} chunk {inputs.chunk}{'' if inputs.wait_for_people else ' without waiting'}"
        )
        return ContactChunkResult(people=3, found=2, attempt=activity.info().attempt, new_people=1)

    @activity.defn(name="messaging-provider-import.fill_contacts_cohort")
    async def fill_cohort(inputs: ContactsCohortInputs) -> int:
        if failure == "fill" and inputs.cohort_id == 7:
            raise ApplicationError("The cohort was deleted", non_retryable=True)
        calls.append(f"fill {inputs.cohort_id}")
        return 1

    @activity.defn(name="messaging-provider-import.fail_contacts_cohort")
    async def fail_cohort(inputs: ContactsCohortInputs) -> None:
        calls.append(f"fail {inputs.cohort_id}")

    @activity.defn(name="messaging-provider-import.record_people_import")
    async def record(inputs: RecordPeopleImportInputs) -> None:
        recorded.append(inputs.outcome)

    @activity.defn(name="messaging-provider-import.finish_run")
    async def finish_run(inputs: ProviderImportRunInputs) -> None:
        calls.append("finish")

    @activity.defn(name="messaging-provider-import.discard_staged_contacts")
    async def discard(inputs: ProviderImportRunInputs) -> None:
        calls.append("discard")

    run_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="provider-import-test",
            workflows=[ProviderImportWorkflow, ProviderContactsImportWorkflow],
            activities=[run_step, import_chunk, fill_cohort, fail_cohort, record, finish_run, discard],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ProviderImportWorkflow.run,
                ProviderImportWorkflowInputs(team_id=1, run_id=run_id, steps=["contacts", "contact_properties"]),
                id=f"provider-import-test-{run_id}",
                task_queue="provider-import-test",
                execution_timeout=timedelta(minutes=5),
            )

    # A segment waits for people the first list's events create, so once those didn't go out it fills right away.
    expected = {
        None: (
            ["prefix chunk 1", "fill 7", "segment chunk 0", "fill 8"],
            ContactsImportOutcome(people=9, found=6, removed=2, failed_lists=0, retried_chunks=1, sent=6, new_people=2),
        ),
        "fill": (
            ["prefix chunk 1", "fail 7", "segment chunk 0", "fill 8"],
            ContactsImportOutcome(people=9, found=6, removed=1, failed_lists=1, retried_chunks=1, sent=6, new_people=2),
        ),
        "partial send": (
            ["fail 7", "segment chunk 0", "fill 8"],
            ContactsImportOutcome(people=6, found=4, removed=1, failed_lists=1, retried_chunks=0, sent=5, new_people=2),
        ),
        "send": (
            ["fail 7", "segment chunk 0 without waiting", "fill 8"],
            ContactsImportOutcome(people=6, found=4, removed=1, failed_lists=1, retried_chunks=0, sent=3, new_people=1),
        ),
    }
    ending, outcome = expected[failure]
    assert calls == ["contacts", "prefix chunk 0", *ending, "contact_properties", "finish", "discard"]
    assert recorded == [outcome]
