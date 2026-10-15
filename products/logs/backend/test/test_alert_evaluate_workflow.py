import uuid
from collections.abc import AsyncIterator

import pytest

import pytest_asyncio
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts_platform.backend.facade.contracts import (
    RECORD_OUTCOMES_ACTIVITY,
    AlertBatchKey,
    AlertEventKind,
    GroupOutcome,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceEvaluationInputs,
    SourceKind,
    SourceOutcomeInputs,
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
    "full_tries, expected_evaluated",
    [
        # The pool frees after two tries, inside the wait budget, so the batch runs in its own tick.
        (2, True),
        # The pool never frees, so the batch gives up and its checks stay due for a later tick.
        (1000, False),
    ],
)
async def test_a_batch_waits_for_a_pool_slot_on_a_timer_before_it_evaluates(
    environment: WorkflowEnvironment, full_tries: int, expected_evaluated: bool
) -> None:
    tries: list[TakeLogsBatchSlotInputs] = []
    evaluated: list[LogsBatchSlot] = []

    @activity.defn(name="take_logs_batch_slot_activity")
    async def take(inputs: TakeLogsBatchSlotInputs) -> LogsBatchAdmission:
        tries.append(inputs)
        if len(tries) <= full_tries:
            return LogsBatchAdmission(due=True)
        return LogsBatchAdmission(due=True, slot=LogsBatchSlot(member=inputs.member, held_until=1.0))

    @activity.defn(name="evaluate_held_logs_batch_activity")
    async def evaluate(inputs: HeldLogsBatchInputs) -> SourceBatchEvaluation:
        evaluated.append(inputs.slot)
        outcome = PlatformAlertOutcome(
            configuration_id=uuid.UUID("01936a2e-0000-7000-8000-000000000001"),
            evaluation_key="slot:2026-09-16T10:00:00+00:00|window:2026-09-16T09:59:45+00:00",
            consecutive_failures=0,
            groups=(GroupOutcome(grouping_key="", kind=AlertEventKind.CHECK, new_state="not_firing", notified=False),),
        )
        return SourceBatchEvaluation(outcomes=(outcome,), deliveries=())

    @activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
    async def record(inputs: SourceOutcomeInputs) -> int:
        return len(inputs.outcomes)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[LogsAlertEvaluateWorkflow],
        activities=[take, evaluate, record],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await environment.client.execute_workflow(
            LogsAlertEvaluateWorkflow.run,
            SourceEvaluationInputs(
                source=SourceKind.LOGS,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
        )

    # Every try names one member, so a retried try finds the slot an earlier one took.
    assert len({t.member for t in tries}) == 1
    if expected_evaluated:
        assert [slot.member for slot in evaluated] == [tries[0].member]
        assert len(tries) == full_tries + 1
        assert not any(t.final for t in tries)
    else:
        assert evaluated == []
        # Only the last try counts the batch as deferred.
        assert [t.final for t in tries].count(True) == 1 and tries[-1].final
