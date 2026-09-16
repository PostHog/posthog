import json
import asyncio
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment

from products.exports.backend.temporal.subscriptions.activities import (
    fetch_due_subscriptions_activity,
    fetch_due_subscriptions_page_activity,
)
from products.exports.backend.temporal.subscriptions.types import (
    DueSubscription,
    FetchDueSubscriptionsActivityInputs,
    FetchDueSubscriptionsPageActivityInputs,
    FetchDueSubscriptionsPageActivityResult,
    ScheduleAllSubscriptionsWorkflowInputs,
    SubscriptionSchedulerCursor,
)
from products.exports.backend.temporal.subscriptions.workflows import ScheduleAllSubscriptionsWorkflow


@pytest.mark.asyncio
@pytest.mark.parametrize("max_subscriptions_per_run", [0, -1])
async def test_legacy_scheduler_fetch_rejects_non_positive_limits(max_subscriptions_per_run: int) -> None:
    with pytest.raises(ApplicationError) as error:
        await ActivityEnvironment().run(
            fetch_due_subscriptions_activity,
            FetchDueSubscriptionsActivityInputs(max_subscriptions_per_run=max_subscriptions_per_run),
        )

    assert error.value.non_retryable is True


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
async def test_scheduler_page_fetch_builds_cursor_from_one_query_snapshot() -> None:
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
            "_remaining_count": 3,
        }
        for subscription_id in range(1, 4)
    ]
    queryset = MagicMock()
    queryset.exclude.return_value = queryset
    queryset.annotate.return_value = queryset
    queryset.order_by.return_value = queryset
    queryset.values.return_value = queryset
    queryset.count.return_value = 2
    queryset.__getitem__.side_effect = lambda page: rows[page]

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.activities.Subscription.objects.filter",
            return_value=queryset,
        ),
        patch("products.exports.backend.temporal.subscriptions.activities.record_scheduler_fetch"),
    ):
        result = await ActivityEnvironment().run(
            fetch_due_subscriptions_page_activity,
            FetchDueSubscriptionsPageActivityInputs(
                due_before="2026-09-11T12:15:00+00:00",
                page_size=2,
            ),
        )

    assert [subscription.subscription_id for subscription in result.subscriptions] == [1, 2]
    assert result.total_count == 3
    assert result.remaining_count == 1
    assert result.next_cursor == SubscriptionSchedulerCursor(
        next_delivery_date=due_at.isoformat(),
        subscription_id=2,
    )


def test_scheduler_parse_inputs_restores_continue_as_new_cursor() -> None:
    parsed = ScheduleAllSubscriptionsWorkflow.parse_inputs(
        [
            json.dumps(
                {
                    "buffer_minutes": 15,
                    "subscriptions_page_size": 100,
                    "due_before": "2026-09-11T12:15:00+00:00",
                    "cursor": {
                        "next_delivery_date": "2026-09-11T12:00:00+00:00",
                        "subscription_id": 100,
                    },
                    "total_count": 250,
                    "processed_count": 100,
                    "page_number": 1,
                }
            )
        ]
    )

    assert parsed.cursor == SubscriptionSchedulerCursor(
        next_delivery_date="2026-09-11T12:00:00+00:00",
        subscription_id=100,
    )


@pytest.mark.asyncio
async def test_scheduler_dispatches_page_concurrently_and_continues_with_progress() -> None:
    subscriptions = [
        DueSubscription(
            subscription_id=subscription_id,
            team_id=42,
            distinct_id="user-1",
            next_delivery_date="2026-09-11T12:00:00+00:00",
            resource_type="insight",
        )
        for subscription_id in range(1, 101)
    ]
    next_cursor = SubscriptionSchedulerCursor(
        next_delivery_date="2026-09-11T12:00:00+00:00",
        subscription_id=100,
    )
    execute_activity = AsyncMock(
        return_value=FetchDueSubscriptionsPageActivityResult(
            subscriptions=subscriptions,
            next_cursor=next_cursor,
            total_count=250,
            remaining_count=150,
        )
    )
    all_starts_submitted = asyncio.Event()
    submitted_count = 0

    async def start_after_all_submitted(*_args, **_kwargs):
        nonlocal submitted_count
        submitted_count += 1
        if submitted_count == len(subscriptions):
            all_starts_submitted.set()
        await all_starts_submitted.wait()
        return MagicMock()

    start_child = AsyncMock(side_effect=start_after_all_submitted)
    execute_child = AsyncMock()
    continue_as_new = MagicMock()
    record_progress = MagicMock()

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
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.record_scheduler_progress",
            new=record_progress,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        await asyncio.wait_for(
            ScheduleAllSubscriptionsWorkflow().run(
                ScheduleAllSubscriptionsWorkflowInputs(due_before="2026-09-11T12:15:00+00:00")
            ),
            timeout=1,
        )

    assert start_child.await_count == 100
    execute_child.assert_not_awaited()
    assert execute_activity.await_args is not None
    fetch_inputs = execute_activity.await_args.args[1]
    assert fetch_inputs.due_before == "2026-09-11T12:15:00+00:00"
    assert fetch_inputs.page_size == 100
    assert fetch_inputs.cursor is None
    assert start_child.await_args_list[0].kwargs["id"] == "process-subscription-1"
    record_progress.assert_called_once_with(
        total_count=250,
        processed_count=100,
        remaining_count=150,
        page_number=1,
        started_count=100,
        already_running_count=0,
        completed=False,
        completed_at=None,
    )
    continue_as_new.assert_called_once_with(
        ScheduleAllSubscriptionsWorkflowInputs(
            buffer_minutes=15,
            subscriptions_page_size=100,
            due_before="2026-09-11T12:15:00+00:00",
            cursor=next_cursor,
            total_count=250,
            processed_count=100,
            page_number=1,
        )
    )


@pytest.mark.asyncio
async def test_scheduler_completes_after_final_page() -> None:
    due_subscription = DueSubscription(
        subscription_id=123,
        team_id=42,
        distinct_id="user-1",
        next_delivery_date="2026-09-11T12:00:00+00:00",
        resource_type="insight",
    )
    execute_activity = AsyncMock(
        return_value=FetchDueSubscriptionsPageActivityResult(
            subscriptions=[due_subscription],
            next_cursor=None,
            total_count=1,
            remaining_count=0,
        )
    )
    start_child = AsyncMock(return_value=MagicMock())
    continue_as_new = MagicMock()
    record_progress = MagicMock()
    completed_at = datetime(2026, 9, 11, 12, 16, tzinfo=UTC)

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
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.record_scheduler_progress",
            new=record_progress,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.now",
            return_value=completed_at,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        await ScheduleAllSubscriptionsWorkflow().run(
            ScheduleAllSubscriptionsWorkflowInputs(due_before="2026-09-11T12:15:00+00:00")
        )

    start_child.assert_awaited_once()
    continue_as_new.assert_not_called()
    record_progress.assert_called_once_with(
        total_count=1,
        processed_count=1,
        remaining_count=0,
        page_number=1,
        started_count=1,
        already_running_count=0,
        completed=True,
        completed_at=completed_at,
    )


@pytest.mark.asyncio
async def test_scheduler_does_not_overlap_an_already_running_subscription() -> None:
    due_subscription = DueSubscription(
        subscription_id=123,
        team_id=42,
        distinct_id="user-1",
        next_delivery_date="2026-09-11T12:00:00+00:00",
        resource_type="insight",
    )
    execute_activity = AsyncMock(
        return_value=FetchDueSubscriptionsPageActivityResult(
            subscriptions=[due_subscription],
            next_cursor=None,
            total_count=1,
            remaining_count=0,
        )
    )
    start_child = AsyncMock(side_effect=WorkflowAlreadyStartedError("process-subscription-123", "process-subscription"))
    record_progress = MagicMock()
    completed_at = datetime(2026, 9, 11, 12, 16, tzinfo=UTC)

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
            "products.exports.backend.temporal.subscriptions.workflows.record_scheduler_progress",
            new=record_progress,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.now",
            return_value=completed_at,
        ),
        patch("products.exports.backend.temporal.subscriptions.workflows.temporalio.workflow.logger.info"),
    ):
        await ScheduleAllSubscriptionsWorkflow().run(
            ScheduleAllSubscriptionsWorkflowInputs(due_before="2026-09-11T12:15:00+00:00")
        )

    assert start_child.await_args is not None
    assert start_child.await_args.kwargs["id"] == "process-subscription-123"
    record_progress.assert_called_once_with(
        total_count=1,
        processed_count=1,
        remaining_count=0,
        page_number=1,
        started_count=0,
        already_running_count=1,
        completed=True,
        completed_at=completed_at,
    )


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

    assert patched.call_args_list == [call("subscription-scheduler-pagination-2026-09")]
    assert execute_activity.await_args is not None
    fetch_inputs = execute_activity.await_args.args[1]
    assert fetch_inputs == {"buffer_minutes": 15}
    execute_child.assert_awaited_once()
    start_child.assert_not_awaited()
