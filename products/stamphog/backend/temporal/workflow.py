"""Stamphog review workflow.

Orchestrates a single PR review: fetch context -> run the whole engine (gates, tier,
familiarity, LLM review) offline in a sandbox -> post the verdict. Gate blocks are now
determined inside the sandbox and surfaced through the verdict output, so there is no
separate server-side gate step. Any unrecoverable error marks the ``ReviewRun`` FAILED.
The workflow only ever moves ``StamphogReviewInput`` (two small fields) between activities;
all bulky data lives on ``ReviewRun.output`` in Postgres.
"""

from __future__ import annotations

import temporalio.workflow
from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.stamphog.backend.temporal.constants import (
    ACTIVITY_RETRY_POLICY,
    FETCH_CONTEXT_TIMEOUT,
    MARK_FAILED_TIMEOUT,
    POST_VERDICT_TIMEOUT,
    RUN_REVIEW_TIMEOUT,
    SANDBOX_RETRY_POLICY,
)

with temporalio.workflow.unsafe.imports_passed_through():
    from products.stamphog.backend.temporal.activities import (
        MarkReviewFailedInput,
        StamphogReviewInput,
        fetch_review_context,
        mark_review_failed,
        post_verdict,
        run_review_in_sandbox,
    )


@workflow.defn(name="stamphog-review")
class StamphogReviewWorkflow(PostHogWorkflow):
    inputs_cls = StamphogReviewInput

    @workflow.run
    async def run(self, input: StamphogReviewInput) -> dict:
        try:
            await workflow.execute_activity(
                fetch_review_context,
                input,
                start_to_close_timeout=FETCH_CONTEXT_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

            await workflow.execute_activity(
                run_review_in_sandbox,
                input,
                start_to_close_timeout=RUN_REVIEW_TIMEOUT,
                retry_policy=SANDBOX_RETRY_POLICY,
            )

            result = await workflow.execute_activity(
                post_verdict,
                input,
                start_to_close_timeout=POST_VERDICT_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            return {"status": "completed", "verdict": result["verdict"]}
        except Exception as e:
            await workflow.execute_activity(
                mark_review_failed,
                MarkReviewFailedInput(
                    review_run_id=input.review_run_id,
                    team_id=input.team_id,
                    error=str(e),
                ),
                start_to_close_timeout=MARK_FAILED_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            raise
