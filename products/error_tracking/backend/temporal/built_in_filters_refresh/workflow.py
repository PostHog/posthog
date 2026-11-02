from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.built_in_filters_refresh.activities import (
        refresh_built_in_filter_rules_activity,
    )
    from products.error_tracking.backend.temporal.built_in_filters_refresh.types import (
        BuiltInFiltersRefreshInputs,
        BuiltInFiltersRefreshResult,
    )

WORKFLOW_NAME = "error-tracking-built-in-filters-refresh"

# A refresh only rewrites rows that are still stale, so a retry repeats no work.
ACTIVITY_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(hours=1)
ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=5)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingBuiltInFiltersRefreshWorkflow(PostHogWorkflow):
    """Rewrite the built-in filter rules whose definitions changed since a team turned them on."""

    inputs_cls = BuiltInFiltersRefreshInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: BuiltInFiltersRefreshInputs | None = None) -> BuiltInFiltersRefreshResult:
        if inputs is None:
            inputs = BuiltInFiltersRefreshInputs()

        return await workflow.execute_activity(
            refresh_built_in_filter_rules_activity,
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
