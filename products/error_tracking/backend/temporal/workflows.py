import json
import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.error_tracking.backend.temporal.activities import (
    ComputeRecommendationInput,
    StaleRecommendation,
    compute_recommendation_activity,
    get_stale_recommendations_activity,
)

MAX_CONCURRENT_TEAMS = 50


@dataclasses.dataclass
class RecommendationsCoordinatorInputs:
    pass


@workflow.defn(name="error-tracking-recommendations-coordinator")
class RecommendationsCoordinatorWorkflow(PostHogWorkflow):
    """Coordinator workflow that finds stale recommendations and fans out computation.

    Runs on a schedule. For each recommendation type, finds teams whose
    recommendations are older than that type's declared interval, then
    processes them in parallel batches.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RecommendationsCoordinatorInputs:
        loaded = json.loads(inputs[0])
        return RecommendationsCoordinatorInputs(**loaded)

    @workflow.run
    async def run(self, inputs: RecommendationsCoordinatorInputs) -> dict[str, Any]:
        stale: list[StaleRecommendation] = await workflow.execute_activity(
            get_stale_recommendations_activity,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=5),
                maximum_interval=timedelta(seconds=30),
            ),
        )

        if not stale:
            return {"teams_processed": 0, "succeeded": 0, "failed": 0}

        succeeded = 0
        failed = 0

        for batch_start in range(0, len(stale), MAX_CONCURRENT_TEAMS):
            batch = stale[batch_start : batch_start + MAX_CONCURRENT_TEAMS]

            results = await asyncio.gather(
                *[
                    workflow.execute_activity(
                        compute_recommendation_activity,
                        ComputeRecommendationInput(
                            team_id=item.team_id,
                            recommendation_type=item.recommendation_type,
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=5),
                            maximum_interval=timedelta(seconds=30),
                        ),
                    )
                    for item in batch
                ],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, BaseException):
                    failed += 1
                elif result:
                    succeeded += 1
                else:
                    failed += 1

        return {
            "teams_processed": len(stale),
            "succeeded": succeeded,
            "failed": failed,
        }
