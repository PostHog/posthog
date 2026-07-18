import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, call, patch

from django.utils import timezone

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.models import ErrorTrackingStackFrame, ErrorTrackingSymbolSet
from products.error_tracking.backend.temporal.symbol_set_cleanup.activities import (
    _delete_symbol_set_contents_with_pacing,
    cleanup_symbol_sets_activity,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup.types import (
    SymbolSetCleanupInputs,
    SymbolSetCleanupResult,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup.workflow import ErrorTrackingSymbolSetCleanupWorkflow


class TestDeleteSymbolSetContentsWithPacing:
    @patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.time.sleep")
    @patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.delete_symbol_set_contents_many")
    def test_paces_between_oversized_sub_batches(self, delete_contents, sleep) -> None:
        storage_ptrs = [f"symbols/{index}" for index in range(1001)]
        delete_contents.return_value = []

        assert _delete_symbol_set_contents_with_pacing(storage_ptrs, pace_first_request=False) == []

        assert delete_contents.call_args_list == [call(storage_ptrs[:1000]), call(storage_ptrs[1000:])]
        sleep.assert_called_once_with(0.1)

    @patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.time.sleep")
    @patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.delete_symbol_set_contents_many")
    def test_paces_before_first_request_across_outer_batches(self, delete_contents, sleep) -> None:
        # A single outer batch of <1000 pointers still paces when it's not the first S3
        # request of the run, so back-to-back outer batches don't hammer S3.
        storage_ptrs = [f"symbols/{index}" for index in range(10)]
        delete_contents.return_value = []

        assert _delete_symbol_set_contents_with_pacing(storage_ptrs, pace_first_request=True) == []

        assert delete_contents.call_args_list == [call(storage_ptrs)]
        sleep.assert_called_once_with(0.1)

    @patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.time.sleep")
    @patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.delete_symbol_set_contents_many")
    def test_does_not_pace_before_the_very_first_request(self, delete_contents, sleep) -> None:
        storage_ptrs = [f"symbols/{index}" for index in range(10)]
        delete_contents.return_value = []

        assert _delete_symbol_set_contents_with_pacing(storage_ptrs, pace_first_request=False) == []

        assert delete_contents.call_args_list == [call(storage_ptrs)]
        sleep.assert_not_called()


class TestSymbolSetCleanupActivity(BaseTest):
    def _create_symbol_set(
        self,
        ref: str,
        *,
        created_at_days_ago: int,
        last_used_days_ago: int | None,
        storage_ptr: str | None = None,
    ) -> ErrorTrackingSymbolSet:
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team,
            ref=ref,
            storage_ptr=storage_ptr,
        )
        created_at = timezone.now() - timedelta(days=created_at_days_ago)
        last_used = timezone.now() - timedelta(days=last_used_days_ago) if last_used_days_ago is not None else None
        ErrorTrackingSymbolSet.objects.filter(id=symbol_set.id).update(created_at=created_at, last_used=last_used)
        symbol_set.refresh_from_db()
        return symbol_set

    def test_deletes_old_used_and_unused_symbol_sets_with_model_semantics(self) -> None:
        old_used = self._create_symbol_set(
            "old-used",
            created_at_days_ago=45,
            last_used_days_ago=31,
            storage_ptr="symbols/old-used",
        )
        self._create_symbol_set(
            "old-unused",
            created_at_days_ago=45,
            last_used_days_ago=None,
            storage_ptr="symbols/old-unused",
        )
        self._create_symbol_set("recent-used", created_at_days_ago=45, last_used_days_ago=5)
        self._create_symbol_set("recent-unused", created_at_days_ago=5, last_used_days_ago=None)

        unresolved_frame = ErrorTrackingStackFrame.objects.create(
            team=self.team,
            raw_id="unresolved",
            symbol_set=old_used,
            contents={},
            resolved=False,
        )
        resolved_frame = ErrorTrackingStackFrame.objects.create(
            team=self.team,
            raw_id="resolved",
            symbol_set=old_used,
            contents={},
            resolved=True,
        )

        with (
            patch(
                "products.error_tracking.backend.temporal.symbol_set_cleanup.activities.delete_symbol_set_contents_many",
                return_value=[],
            ) as delete_contents,
            patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.close_old_connections"),
        ):
            result = cleanup_symbol_sets_activity(SymbolSetCleanupInputs(batch_size=10, total_per_run=10))

        assert result == SymbolSetCleanupResult(objects_processed=2, objects_deleted=2, objects_failed=0)
        assert set(ErrorTrackingSymbolSet.objects.values_list("ref", flat=True)) == {"recent-used", "recent-unused"}
        assert not ErrorTrackingStackFrame.objects.filter(id=unresolved_frame.id).exists()
        resolved_frame.refresh_from_db()
        assert resolved_frame.symbol_set_id is None
        assert {storage_ptr for call in delete_contents.call_args_list for storage_ptr in call.args[0]} == {
            "symbols/old-used",
            "symbols/old-unused",
        }
        assert delete_contents.call_count == 1

    def test_delete_unused_false_only_deletes_old_used_symbol_sets(self) -> None:
        self._create_symbol_set("old-used", created_at_days_ago=45, last_used_days_ago=31)
        self._create_symbol_set("old-unused", created_at_days_ago=45, last_used_days_ago=None)

        with patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.close_old_connections"):
            result = cleanup_symbol_sets_activity(SymbolSetCleanupInputs(delete_unused=False))

        assert result == SymbolSetCleanupResult(objects_processed=1, objects_deleted=1, objects_failed=0)
        assert list(ErrorTrackingSymbolSet.objects.values_list("ref", flat=True)) == ["old-unused"]

    def test_storage_delete_failures_are_reported_separately(self) -> None:
        self._create_symbol_set(
            "old-used", created_at_days_ago=45, last_used_days_ago=31, storage_ptr="symbols/old-used"
        )

        with (
            patch(
                "products.error_tracking.backend.temporal.symbol_set_cleanup.activities.delete_symbol_set_contents_many",
                return_value=["symbols/old-used"],
            ),
            patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.close_old_connections"),
        ):
            result = cleanup_symbol_sets_activity(SymbolSetCleanupInputs(batch_size=10, total_per_run=10))

        assert result == SymbolSetCleanupResult(
            objects_processed=1,
            objects_deleted=1,
            objects_failed=0,
            storage_objects_failed=1,
        )
        assert ErrorTrackingSymbolSet.objects.count() == 0

    def test_dry_run_returns_eligible_count_without_deleting(self) -> None:
        self._create_symbol_set("old-used", created_at_days_ago=45, last_used_days_ago=31)
        self._create_symbol_set("old-unused", created_at_days_ago=45, last_used_days_ago=None)

        with patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.close_old_connections"):
            result = cleanup_symbol_sets_activity(SymbolSetCleanupInputs(dry_run=True))

        assert result == SymbolSetCleanupResult(
            objects_processed=0,
            objects_deleted=0,
            objects_failed=0,
            eligible_count=2,
        )
        assert ErrorTrackingSymbolSet.objects.count() == 2

    def test_respects_total_per_run(self) -> None:
        for index in range(3):
            self._create_symbol_set(f"old-used-{index}", created_at_days_ago=45, last_used_days_ago=31)

        with patch("products.error_tracking.backend.temporal.symbol_set_cleanup.activities.close_old_connections"):
            result = cleanup_symbol_sets_activity(SymbolSetCleanupInputs(total_per_run=2, batch_size=1))

        assert result == SymbolSetCleanupResult(objects_processed=2, objects_deleted=2, objects_failed=0)
        assert ErrorTrackingSymbolSet.objects.count() == 1


async def _run_workflow_with_mock_activity(
    inputs: SymbolSetCleanupInputs | None,
    activity_result: Callable[[SymbolSetCleanupInputs], SymbolSetCleanupResult],
) -> tuple[SymbolSetCleanupResult, list[SymbolSetCleanupInputs]]:
    captured: list[SymbolSetCleanupInputs] = []

    @activity.defn(name="cleanup_symbol_sets_activity")
    async def mock_activity(activity_inputs: SymbolSetCleanupInputs) -> SymbolSetCleanupResult:
        captured.append(activity_inputs)
        return activity_result(activity_inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingSymbolSetCleanupWorkflow],
            activities=[mock_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ErrorTrackingSymbolSetCleanupWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return result, captured


class TestSymbolSetCleanupWorkflow:
    @freeze_time("2026-01-31T00:00:00Z")
    def test_parse_defaults_match_dagster_config(self) -> None:
        assert ErrorTrackingSymbolSetCleanupWorkflow.parse_inputs([]) == SymbolSetCleanupInputs(
            days_old=30,
            delete_unused=True,
            total_per_run=1000000,
            batch_size=10000,
            parallelism=8,
            dry_run=False,
        )

    @pytest.mark.asyncio
    async def test_workflow_splits_total_limit_across_parallel_activities(self) -> None:
        inputs = SymbolSetCleanupInputs(total_per_run=10, batch_size=5, parallelism=3)

        result, activity_inputs = await _run_workflow_with_mock_activity(
            inputs,
            lambda activity_inputs: SymbolSetCleanupResult(
                objects_processed=activity_inputs.total_per_run,
                objects_deleted=activity_inputs.total_per_run,
                objects_failed=0,
            ),
        )

        assert result == SymbolSetCleanupResult(objects_processed=10, objects_deleted=10, objects_failed=0)
        assert sorted(activity_input.total_per_run for activity_input in activity_inputs) == [3, 3, 4]
        assert all(activity_input.batch_size == 5 for activity_input in activity_inputs)
        assert all(activity_input.parallelism == 1 for activity_input in activity_inputs)

    @pytest.mark.asyncio
    async def test_workflow_runs_dry_run_once(self) -> None:
        inputs = SymbolSetCleanupInputs(
            days_old=10,
            delete_unused=False,
            total_per_run=100,
            batch_size=5,
            parallelism=3,
            dry_run=True,
        )
        expected = SymbolSetCleanupResult(objects_processed=0, objects_deleted=0, objects_failed=0, eligible_count=3)

        result, activity_inputs = await _run_workflow_with_mock_activity(inputs, lambda _: expected)

        assert result == expected
        assert activity_inputs == [inputs]

    @pytest.mark.asyncio
    async def test_workflow_preserves_single_activity_for_unpatched_histories(self) -> None:
        inputs = SymbolSetCleanupInputs(total_per_run=100, parallelism=4)
        expected = SymbolSetCleanupResult(objects_processed=100, objects_deleted=100, objects_failed=0)

        with (
            patch(
                "products.error_tracking.backend.temporal.symbol_set_cleanup.workflow.workflow.patched",
                return_value=False,
            ),
            patch(
                "products.error_tracking.backend.temporal.symbol_set_cleanup.workflow.workflow.execute_activity",
                new_callable=AsyncMock,
                return_value=expected,
            ) as execute_activity,
        ):
            result = await ErrorTrackingSymbolSetCleanupWorkflow().run(inputs)

        assert result == expected
        execute_activity.assert_awaited_once()
        assert execute_activity.call_args.args[1] == inputs
