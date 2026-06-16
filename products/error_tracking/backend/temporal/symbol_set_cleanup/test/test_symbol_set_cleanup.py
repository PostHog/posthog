import uuid
from datetime import timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.models import ErrorTrackingStackFrame, ErrorTrackingSymbolSet
from products.error_tracking.backend.temporal.symbol_set_cleanup.activities import cleanup_symbol_sets_activity
from products.error_tracking.backend.temporal.symbol_set_cleanup.types import (
    SymbolSetCleanupInputs,
    SymbolSetCleanupResult,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup.workflow import ErrorTrackingSymbolSetCleanupWorkflow


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
    activity_result: SymbolSetCleanupResult,
) -> tuple[SymbolSetCleanupResult, SymbolSetCleanupInputs]:
    captured: dict[str, SymbolSetCleanupInputs] = {}

    @activity.defn(name="cleanup_symbol_sets_activity")
    async def mock_activity(activity_inputs: SymbolSetCleanupInputs) -> SymbolSetCleanupResult:
        captured["inputs"] = activity_inputs
        return activity_result

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

    return result, captured["inputs"]


class TestSymbolSetCleanupWorkflow:
    @freeze_time("2026-01-31T00:00:00Z")
    def test_parse_defaults_match_dagster_config(self) -> None:
        assert ErrorTrackingSymbolSetCleanupWorkflow.parse_inputs([]) == SymbolSetCleanupInputs(
            days_old=30,
            delete_unused=True,
            total_per_run=500000,
            batch_size=10000,
            dry_run=False,
        )

    @pytest.mark.asyncio
    async def test_workflow_calls_activity_with_defaults(self) -> None:
        expected = SymbolSetCleanupResult(objects_processed=1, objects_deleted=1, objects_failed=0)

        result, activity_inputs = await _run_workflow_with_mock_activity(None, expected)

        assert result == expected
        assert activity_inputs == SymbolSetCleanupInputs()

    @pytest.mark.asyncio
    async def test_workflow_forwards_inputs(self) -> None:
        inputs = SymbolSetCleanupInputs(days_old=10, delete_unused=False, total_per_run=100, batch_size=5, dry_run=True)
        expected = SymbolSetCleanupResult(objects_processed=0, objects_deleted=0, objects_failed=0, eligible_count=3)

        result, activity_inputs = await _run_workflow_with_mock_activity(inputs, expected)

        assert result == expected
        assert activity_inputs == inputs
