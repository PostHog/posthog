import json
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment

from products.exports.backend.temporal.subscriptions.activities import fetch_due_subscriptions_page_activity
from products.exports.backend.temporal.subscriptions.types import (
    DueSubscription,
    FetchDueSubscriptionsActivityInputs,
    FetchDueSubscriptionsPageActivityInputs,
    FetchDueSubscriptionsPageActivityResult,
    ScheduleAllSubscriptionsWorkflowInputs,
    SubscriptionSchedulerCursor,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
)
from products.exports.backend.temporal.subscriptions.workflows import (
    ProcessAISubscriptionWorkflow,
    ProcessSubscriptionWorkflow,
    ScheduleAllSubscriptionsWorkflow,
)


class _ContinueAsNewCalled(Exception):
    pass


def _due_subscription(subscription_id: int) -> DueSubscription:
    return DueSubscription(
        subscription_id=subscription_id,
        team_id=42,
        distinct_id="user-1",
        next_delivery_date="2026-09-11T12:00:00+00:00",
        resource_type="insight",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [0, -1])
async def test_scheduler_page_fetch_rejects_non_positive_limits(page_size: int) -> None:
    with pytest.raises(ApplicationError) as error:
        await ActivityEnvironment().run(
            fetch_due_subscriptions_page_activity,
            FetchDueSubscriptionsPageActivityInputs(
                due_before="2026-09-11T12:15:00+00:00",
                page_size=page_size,
            ),
        )

    assert error.value.non_retryable is True


@pytest.mark.asyncio
async def test_scheduler_page_fetch_builds_stable_cursor_without_counting_the_cohort() -> None:
    due_at = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    rows = [
        {
            "id": subscription_id,
            "team_id": 42,
            "created_by__distinct_id": "user-1",
            "next_delivery_date": due_at,
            "insight_id": subscription_id,
            "dashboard_id": None,
            "prompt": None,
        }
        for subscription_id in range(1, 4)
    ]
    queryset = MagicMock()
    queryset.exclude.return_value = queryset
    queryset.order_by.return_value = queryset
    queryset.values.return_value = queryset
    queryset.__getitem__.side_effect = lambda page: rows[page]

    with patch(
        "products.exports.backend.temporal.subscriptions.activities.Subscription.objects.filter",
        return_value=queryset,
    ):
        result = await ActivityEnvironment().run(
            fetch_due_subscriptions_page_activity,
            FetchDueSubscriptionsPageActivityInputs(
                due_before="2026-09-11T12:15:00+00:00",
                page_size=2,
            ),
        )

    assert [subscription.subscription_id for subscription in result.subscriptions] == [1, 2]
    assert result.next_cursor == SubscriptionSchedulerCursor(
        next_delivery_date=due_at.isoformat(),
        subscription_id=2,
    )
    queryset.annotate.assert_not_called()
    queryset.count.assert_not_called()


def test_scheduler_parse_inputs_restores_continue_as_new_cursor() -> None:
    parsed = ScheduleAllSubscriptionsWorkflow.parse_inputs(
        [
            json.dumps(
                {
                    "buffer_minutes": 15,
                    "subscriptions_page_size": 500,
                    "due_before": "2026-09-11T12:15:00+00:00",
                    "cursor": {
                        "next_delivery_date": "2026-09-11T12:00:00+00:00",
                        "subscription_id": 100,
                    },
                }
            )
        ]
    )

    assert parsed.cursor == SubscriptionSchedulerCursor(
        next_delivery_date="2026-09-11T12:00:00+00:00",
        subscription_id=100,
    )


@pytest.mark.asyncio
async def test_scheduler_continues_after_child_starts_are_accepted() -> None:
    subscriptions = [_due_subscription(subscription_id) for subscription_id in range(1, 4)]
    next_cursor = SubscriptionSchedulerCursor(
        next_delivery_date="2026-09-11T12:00:00+00:00",
        subscription_id=3,
    )
    execute_activity = AsyncMock(
        return_value=FetchDueSubscriptionsPageActivityResult(subscriptions=subscriptions, next_cursor=next_cursor)
    )
    start_child = AsyncMock()
    execute_child = AsyncMock()
    continue_as_new = MagicMock(side_effect=_ContinueAsNewCalled)

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
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.continue_as_new",
            new=continue_as_new,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        with pytest.raises(_ContinueAsNewCalled):
            await ScheduleAllSubscriptionsWorkflow().run(
                ScheduleAllSubscriptionsWorkflowInputs(due_before="2026-09-11T12:15:00+00:00")
            )

    assert start_child.await_count == 3
    execute_child.assert_not_awaited()
    continue_as_new.assert_called_once_with(
        ScheduleAllSubscriptionsWorkflowInputs(
            buffer_minutes=15,
            subscriptions_page_size=500,
            due_before="2026-09-11T12:15:00+00:00",
            cursor=next_cursor,
            failed_start_count=0,
        )
    )


@pytest.mark.asyncio
async def test_scheduler_start_failure_does_not_truncate_later_pages() -> None:
    next_cursor = SubscriptionSchedulerCursor(
        next_delivery_date="2026-09-11T12:00:00+00:00",
        subscription_id=2,
    )
    execute_activity = AsyncMock(
        return_value=FetchDueSubscriptionsPageActivityResult(
            subscriptions=[_due_subscription(1), _due_subscription(2)],
            next_cursor=next_cursor,
        )
    )
    start_child = AsyncMock(side_effect=[RuntimeError("start failed"), None])
    continue_as_new = MagicMock(side_effect=_ContinueAsNewCalled)

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
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.patched",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.continue_as_new",
            new=continue_as_new,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.warning"),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        with pytest.raises(_ContinueAsNewCalled):
            await ScheduleAllSubscriptionsWorkflow().run(
                ScheduleAllSubscriptionsWorkflowInputs(due_before="2026-09-11T12:15:00+00:00")
            )

    assert start_child.await_count == 2
    continue_as_new.assert_called_once_with(
        ScheduleAllSubscriptionsWorkflowInputs(
            buffer_minutes=15,
            subscriptions_page_size=500,
            due_before="2026-09-11T12:15:00+00:00",
            cursor=next_cursor,
            failed_start_count=1,
        )
    )


@pytest.mark.asyncio
async def test_scheduler_reports_start_failures_after_the_final_page() -> None:
    execute_activity = AsyncMock(
        return_value=FetchDueSubscriptionsPageActivityResult(subscriptions=[_due_subscription(2)], next_cursor=None)
    )
    start_child = AsyncMock()

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
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.patched",
            return_value=True,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        with pytest.raises(ApplicationError, match="1 subscription delivery workflows failed to start"):
            await ScheduleAllSubscriptionsWorkflow().run(
                ScheduleAllSubscriptionsWorkflowInputs(
                    due_before="2026-09-11T12:15:00+00:00",
                    failed_start_count=1,
                )
            )

    start_child.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_treats_an_open_child_as_already_dispatched() -> None:
    execute_activity = AsyncMock(
        return_value=FetchDueSubscriptionsPageActivityResult(subscriptions=[_due_subscription(123)], next_cursor=None)
    )
    start_child = AsyncMock(side_effect=WorkflowAlreadyStartedError("process-subscription-123", "process-subscription"))

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
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.patched",
            return_value=True,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        await ScheduleAllSubscriptionsWorkflow().run(
            ScheduleAllSubscriptionsWorkflowInputs(due_before="2026-09-11T12:15:00+00:00")
        )

    start_child.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_preserves_waiting_behavior_when_replaying_legacy_runs() -> None:
    start_child = AsyncMock()
    execute_child = AsyncMock(return_value=None)
    execute_activity = AsyncMock(return_value=[_due_subscription(123)])

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

    assert patched.call_args_list == [call("subscription-scheduler-pagination-2026-09")]
    assert execute_activity.await_args is not None
    assert execute_activity.await_args.args[1] == FetchDueSubscriptionsActivityInputs(buffer_minutes=15)
    execute_child.assert_awaited_once()
    start_child.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_class", [ProcessSubscriptionWorkflow, ProcessAISubscriptionWorkflow])
async def test_stale_scheduled_occurrence_returns_before_delivery(workflow_class: type) -> None:
    inputs = TrackedSubscriptionInputs(
        subscription_id=123,
        team_id=42,
        distinct_id="user-1",
        trigger_type=SubscriptionTriggerType.SCHEDULED,
        scheduled_at="2026-09-11T12:00:00+00:00",
        resource_type="insight",
    )
    execute_activity = AsyncMock(return_value=False)

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.execute_activity",
            new=execute_activity,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.patched",
            return_value=True,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        await workflow_class().run(inputs)

    execute_activity.assert_awaited_once()
    assert execute_activity.await_args is not None
    assert execute_activity.await_args.args[1].subscription_id == 123
    assert execute_activity.await_args.args[1].scheduled_at == "2026-09-11T12:00:00+00:00"
