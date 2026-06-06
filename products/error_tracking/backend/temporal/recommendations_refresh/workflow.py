import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.recommendations_refresh.activities import (
        get_teams_with_recent_exceptions_activity,
        refresh_recommendations_batch_activity,
    )
    from products.error_tracking.backend.temporal.recommendations_refresh.types import (
        RecommendationsRefreshInputs,
        RecommendationsRefreshResult,
        RefreshBatchInputs,
    )

WORKFLOW_NAME = "error-tracking-recommendations-refresh"

ENUMERATE_RETRY_POLICY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))
ENUMERATE_TIMEOUT = timedelta(minutes=5)

BATCH_RETRY_POLICY = common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))
BATCH_START_TO_CLOSE_TIMEOUT = timedelta(minutes=30)
BATCH_HEARTBEAT_TIMEOUT = timedelta(minutes=2)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingRecommendationsRefreshWorkflow(PostHogWorkflow):
    inputs_cls = RecommendationsRefreshInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: RecommendationsRefreshInputs | None = None) -> RecommendationsRefreshResult:
        if inputs is None:
            inputs = RecommendationsRefreshInputs()

        team_ids = await workflow.execute_activity(
            get_teams_with_recent_exceptions_activity,
            inputs,
            start_to_close_timeout=ENUMERATE_TIMEOUT,
            retry_policy=ENUMERATE_RETRY_POLICY,
        )

        if not team_ids:
            return RecommendationsRefreshResult(teams_total=0, recommendations_kicked=0, batches_failed=0)

        batches = [team_ids[i : i + inputs.batch_size] for i in range(0, len(team_ids), inputs.batch_size)]

        kicked = 0
        batches_failed = 0
        # Process batches in concurrency-limited waves. Each wave runs up to
        # max_concurrent_batches activities at once, capping in-flight CH/PG load.
        for wave_start in range(0, len(batches), inputs.max_concurrent_batches):
            wave = batches[wave_start : wave_start + inputs.max_concurrent_batches]
            results = await asyncio.gather(
                *[
                    workflow.execute_activity(
                        refresh_recommendations_batch_activity,
                        RefreshBatchInputs(team_ids=batch),
                        start_to_close_timeout=BATCH_START_TO_CLOSE_TIMEOUT,
                        heartbeat_timeout=BATCH_HEARTBEAT_TIMEOUT,
                        retry_policy=BATCH_RETRY_POLICY,
                    )
                    for batch in wave
                ],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    batches_failed += 1
                    workflow.logger.warning(
                        "error_tracking.recommendations_refresh.batch_failed",
                        extra={"error": str(result)},
                    )
                    continue
                kicked += result.recommendations_kicked

        return RecommendationsRefreshResult(
            teams_total=len(team_ids),
            recommendations_kicked=kicked,
            batches_failed=batches_failed,
        )
