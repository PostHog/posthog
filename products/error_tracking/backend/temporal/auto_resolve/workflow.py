import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.auto_resolve.activities import (
        auto_resolve_batch_activity,
        get_auto_resolve_team_batches_activity,
    )
    from products.error_tracking.backend.temporal.auto_resolve.types import (
        AutoResolveBatchInputs,
        AutoResolveBatchResult,
        AutoResolveInputs,
        AutoResolveResult,
    )

WORKFLOW_NAME = "error-tracking-auto-resolve"

ENUMERATE_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))
ENUMERATE_TIMEOUT = timedelta(minutes=5)

# Resolving is idempotent (only still-active issues are touched), so a retried batch is safe.
BATCH_RETRY_POLICY = common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))
BATCH_START_TO_CLOSE_TIMEOUT = timedelta(minutes=30)
BATCH_HEARTBEAT_TIMEOUT = timedelta(minutes=5)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingAutoResolveWorkflow(PostHogWorkflow):
    inputs_cls = AutoResolveInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: AutoResolveInputs | None = None) -> AutoResolveResult:
        if inputs is None:
            inputs = AutoResolveInputs()

        batches = await workflow.execute_activity(
            get_auto_resolve_team_batches_activity,
            inputs,
            start_to_close_timeout=ENUMERATE_TIMEOUT,
            retry_policy=ENUMERATE_RETRY_POLICY,
        )

        semaphore = asyncio.Semaphore(inputs.max_concurrent_batches)

        async def run_batch(batch: list[int]) -> AutoResolveBatchResult:
            async with semaphore:
                return await workflow.execute_activity(
                    auto_resolve_batch_activity,
                    AutoResolveBatchInputs(team_ids=batch),
                    start_to_close_timeout=BATCH_START_TO_CLOSE_TIMEOUT,
                    heartbeat_timeout=BATCH_HEARTBEAT_TIMEOUT,
                    retry_policy=BATCH_RETRY_POLICY,
                )

        results = await asyncio.gather(*[run_batch(batch) for batch in batches], return_exceptions=True)

        teams_total = 0
        teams_failed = 0
        issues_resolved = 0
        batches_failed = 0
        for result in results:
            if isinstance(result, BaseException):
                batches_failed += 1
                workflow.logger.warning("error_tracking.auto_resolve.batch_failed", extra={"error": str(result)})
                continue
            teams_total += result.teams_processed
            teams_failed += result.teams_failed
            issues_resolved += result.issues_resolved

        return AutoResolveResult(
            teams_total=teams_total,
            teams_failed=teams_failed,
            issues_resolved=issues_resolved,
            batches_failed=batches_failed,
        )
