import json
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

ACTIVITY_RETRY_POLICY = common.RetryPolicy(maximum_attempts=1)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(hours=2)


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

        return await workflow.execute_activity(
            cleanup_symbol_sets_activity,
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
