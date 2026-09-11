import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from products.exports.backend.temporal.subscriptions.types import (
    DueSubscription,
    ScheduleAllSubscriptionsWorkflowInputs,
)
from products.exports.backend.temporal.subscriptions.workflows import ScheduleAllSubscriptionsWorkflow


@pytest.mark.asyncio
async def test_scheduler_starts_children_without_waiting_for_completion() -> None:
    due_subscription = DueSubscription(
        subscription_id=123,
        team_id=42,
        distinct_id="user-1",
        next_delivery_date="2026-09-11T12:00:00+00:00",
        resource_type="insight",
    )
    execute_activity = AsyncMock(return_value=[due_subscription])
    start_child = AsyncMock(return_value=MagicMock())
    execute_child = AsyncMock()

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.execute_activity",
            new=execute_activity,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.start_child_workflow",
            new=start_child,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.execute_child_workflow",
            new=execute_child,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.patched",
            return_value=True,
        ),
    ):
        await ScheduleAllSubscriptionsWorkflow().run(ScheduleAllSubscriptionsWorkflowInputs())

    start_child.assert_awaited_once()
    execute_child.assert_not_awaited()
    assert execute_activity.await_args is not None
    fetch_inputs = execute_activity.await_args.args[1]
    assert fetch_inputs.max_subscriptions_per_run == 500


@pytest.mark.asyncio
async def test_scheduler_preserves_waiting_behavior_when_replaying_legacy_runs() -> None:
    due_subscription = DueSubscription(
        subscription_id=123,
        team_id=42,
        distinct_id="user-1",
        next_delivery_date="2026-09-11T12:00:00+00:00",
        resource_type="insight",
    )
    start_child = AsyncMock()
    execute_child = AsyncMock(return_value=None)
    execute_activity = AsyncMock(return_value=[due_subscription])

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.execute_activity",
            new=execute_activity,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.start_child_workflow",
            new=start_child,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.execute_child_workflow",
            new=execute_child,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.patched",
            return_value=False,
        ) as patched,
    ):
        await ScheduleAllSubscriptionsWorkflow().run(ScheduleAllSubscriptionsWorkflowInputs())

    assert patched.call_args_list == [
        call("subscription-scheduler-bounded-input-2026-09"),
        call("subscription-scheduler-fire-and-forget-2026-09"),
    ]
    assert execute_activity.await_args is not None
    fetch_inputs = execute_activity.await_args.args[1]
    assert fetch_inputs == {"buffer_minutes": 15}
    execute_child.assert_awaited_once()
    start_child.assert_not_awaited()
