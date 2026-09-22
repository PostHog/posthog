import uuid

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.temporal.alerts.types import (
    THREAD_BUSY_ERROR_TYPE,
    AlertDeliveryWorkflowInputs,
    AlertDeliveryWorkflowResult,
)
from products.error_tracking.backend.temporal.alerts.workflow import ErrorTrackingAlertDeliveryWorkflow


def _inputs() -> AlertDeliveryWorkflowInputs:
    return AlertDeliveryWorkflowInputs(
        notification_id=str(uuid.uuid4()),
        team_id=1,
        issue_id=str(uuid.uuid4()),
        event="$error_tracking_issue_resolved",
        status="Resolved",
    )


async def _run(deliver, *, expect_failure: bool = False):
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingAlertDeliveryWorkflow],
            activities=[deliver],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await environment.client.start_workflow(
                ErrorTrackingAlertDeliveryWorkflow.run,
                _inputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            if expect_failure:
                with pytest.raises(WorkflowFailureError) as raised:
                    await handle.result()
                return raised.value
            return await handle.result()


@pytest.mark.asyncio
async def test_busy_thread_is_waited_out_without_spending_activity_attempts() -> None:
    attempts: list[int] = []

    @activity.defn(name="deliver_alert_notifications_activity")
    async def deliver(_: AlertDeliveryWorkflowInputs) -> int:
        # Every call is attempt 1: the wait happens in the workflow, not in the retry policy.
        attempts.append(activity.info().attempt)
        if len(attempts) < 3:
            raise ApplicationError("busy", type=THREAD_BUSY_ERROR_TYPE, non_retryable=True)
        return 1

    result = await _run(deliver)

    assert result == AlertDeliveryWorkflowResult(deliveries=1)
    assert attempts == [1, 1, 1]


@pytest.mark.asyncio
async def test_busy_wait_gives_up_after_its_deadline() -> None:
    calls = 0

    @activity.defn(name="deliver_alert_notifications_activity")
    async def deliver(_: AlertDeliveryWorkflowInputs) -> int:
        nonlocal calls
        calls += 1
        raise ApplicationError("busy", type=THREAD_BUSY_ERROR_TYPE, non_retryable=True)

    failure = await _run(deliver, expect_failure=True)

    assert isinstance(failure.cause, ActivityError)
    assert isinstance(failure.cause.cause, ApplicationError)
    assert failure.cause.cause.type == THREAD_BUSY_ERROR_TYPE
    # Ten minutes of five-second waits, then the busy error surfaces as the workflow failure.
    assert calls > 100
