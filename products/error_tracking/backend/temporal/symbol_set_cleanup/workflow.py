import json
import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.symbol_set_cleanup.activities import cleanup_symbol_sets_activity
    from products.error_tracking.backend.temporal.symbol_set_cleanup.types import (
        SymbolSetCleanupInputs,
        SymbolSetCleanupResult,
    )

WORKFLOW_NAME = "error-tracking-symbol-set-cleanup"
PARALLEL_CLEANUP_PATCH_ID = "error-tracking-parallel-symbol-set-cleanup"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(maximum_attempts=1)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(hours=2)


def _activity_inputs(inputs: SymbolSetCleanupInputs) -> list[SymbolSetCleanupInputs]:
    if inputs.dry_run or inputs.total_per_run <= 0:
        return [inputs]

    parallelism = max(1, min(inputs.parallelism, inputs.total_per_run))
    per_activity_limit, remainder = divmod(inputs.total_per_run, parallelism)
    return [
        SymbolSetCleanupInputs(
            days_old=inputs.days_old,
            delete_unused=inputs.delete_unused,
            total_per_run=per_activity_limit + (1 if index < remainder else 0),
            batch_size=inputs.batch_size,
            parallelism=1,
            dry_run=False,
        )
        for index in range(parallelism)
    ]


def _combine_results(results: list[SymbolSetCleanupResult]) -> SymbolSetCleanupResult:
    eligible_counts = [result.eligible_count for result in results if result.eligible_count is not None]
    return SymbolSetCleanupResult(
        objects_processed=sum(result.objects_processed for result in results),
        objects_deleted=sum(result.objects_deleted for result in results),
        objects_failed=sum(result.objects_failed for result in results),
        storage_objects_failed=sum(result.storage_objects_failed for result in results),
        eligible_count=sum(eligible_counts) if eligible_counts else None,
    )


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingSymbolSetCleanupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SymbolSetCleanupInputs:
        if inputs:
            data = json.loads(inputs[0])
            return SymbolSetCleanupInputs(**data)
        return SymbolSetCleanupInputs()

    @workflow.run
    async def run(self, inputs: SymbolSetCleanupInputs | None = None) -> SymbolSetCleanupResult:
        if inputs is None:
            inputs = SymbolSetCleanupInputs()

        if not workflow.patched(PARALLEL_CLEANUP_PATCH_ID):
            return await workflow.execute_activity(
                cleanup_symbol_sets_activity,
                inputs,
                start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

        results = await asyncio.gather(
            *[
                workflow.execute_activity(
                    cleanup_symbol_sets_activity,
                    activity_inputs,
                    start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                for activity_inputs in _activity_inputs(inputs)
            ]
        )
        return _combine_results(results)
