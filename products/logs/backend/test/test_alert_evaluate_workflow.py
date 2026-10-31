import uuid
import datetime as dt
from collections.abc import AsyncIterator

import pytest

import pytest_asyncio
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts_platform.backend.facade.contracts import (
    AlertBatchKey,
    SourceBatchEvaluation,
    SourceEvaluationInputs,
    SourceKind,
)
from products.logs.backend.temporal.alert_evaluate import (
    HeldLogsBatchInputs,
    LogsAlertEvaluateWorkflow,
    TakeLogsBatchSlotInputs,
)
from products.logs.backend.temporal.batch_slot import LogsBatchAdmission, LogsBatchSlot

QUEUE = "test-logs-platform-evaluation"


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.parametrize(
    "full_tries, expected_evaluated, evaluation_fails",
    [
        # The pool frees after two tries, inside the wait budget, so the batch runs in its own tick.
        (2, True, False),
        # The pool never frees, so the batch gives up and its checks stay due for a later tick.
        (1000, False, False),
        # The evaluation fails, for example by timing out in the queue, so the workflow frees the slot.
        (0, True, True),
    ],
)
async def test_a_batch_waits_for_a_pool_slot_on_a_timer_before_it_evaluates(
    environment: WorkflowEnvironment, full_tries: int, expected_evaluated: bool, evaluation_fails: bool
) -> None:
    tries: list[TakeLogsBatchSlotInputs] = []
    evaluated: list[LogsBatchSlot] = []
    released: list[LogsBatchSlot] = []

    @activity.defn(name="take_logs_batch_slot_activity")
    async def take(inputs: TakeLogsBatchSlotInputs) -> LogsBatchAdmission:
        tries.append(inputs)
        if len(tries) <= full_tries:
            return LogsBatchAdmission(due=True)
        return LogsBatchAdmission(due=True, slot=LogsBatchSlot(member=inputs.member, held_until=1.0))

    @activity.defn(name="evaluate_held_logs_batch_activity")
    async def evaluate(inputs: HeldLogsBatchInputs) -> SourceBatchEvaluation:
        evaluated.append(inputs.slot)
        if evaluation_fails:
            raise ApplicationError("evaluation failed", non_retryable=True)
        return SourceBatchEvaluation(outcomes=(), deliveries=())

    @activity.defn(name="release_logs_batch_slot_activity")
    async def release(held: LogsBatchSlot) -> None:
        released.append(held)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[LogsAlertEvaluateWorkflow],
        activities=[take, evaluate, release],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        run = environment.client.execute_workflow(
            LogsAlertEvaluateWorkflow.run,
            SourceEvaluationInputs(
                source=SourceKind.LOGS,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
            execution_timeout=dt.timedelta(minutes=5),
        )
        if evaluation_fails:
            with pytest.raises(WorkflowFailureError):
                await run
        else:
            await run

    # Every try names one member, so a retried try finds the slot an earlier one took.
    assert len({t.member for t in tries}) == 1
    # Only the first try reads whether the batch is due.
    assert [t.first for t in tries][:2] == [True, False][: len(tries)]
    if expected_evaluated:
        assert [slot.member for slot in evaluated] == [tries[0].member]
        assert len(tries) == full_tries + 1
        assert not any(t.final for t in tries)
        assert released == (evaluated if evaluation_fails else [])
    else:
        assert evaluated == []
        # Only the last try counts the batch as deferred.
        assert [t.final for t in tries].count(True) == 1 and tries[-1].final
