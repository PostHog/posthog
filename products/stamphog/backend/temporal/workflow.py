"""Stamphog review workflow.

Orchestrates a single PR review: fetch context -> run the whole engine (gates, tier,
familiarity, LLM review) offline in a sandbox -> post the verdict. Gate blocks are now
determined inside the sandbox and surfaced through the verdict output, so there is no
separate server-side gate step. Any unrecoverable error marks the ``ReviewRun`` FAILED.
The workflow only ever moves ``StamphogReviewInput`` (two small fields) between activities;
all bulky data lives on ``ReviewRun.output`` in Postgres.
"""

from __future__ import annotations

import asyncio

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
    STAMPHOG_BOT_REVIEW_MAX_POLLS,
    STAMPHOG_BOT_REVIEW_POLL_SECONDS,
)

with temporalio.workflow.unsafe.imports_passed_through():
    from products.stamphog.backend.temporal.activities import (
        MarkReviewFailedInput,
        StamphogReviewInput,
        dismiss_stale_approvals,
        fetch_review_context,
        list_in_flight_reviewer_bots,
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
            # Dismiss any approval from an earlier head FIRST — before context fetch, not just before
            # the re-review. Fail-closed ordering: if any later step exhausts retries and the run is
            # marked failed, the stale approval is already gone rather than left satisfying required
            # reviews over unreviewed commits. The activity needs only the run row, nothing fetched.
            await workflow.execute_activity(
                dismiss_stale_approvals,
                input,
                start_to_close_timeout=POST_VERDICT_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

            await workflow.execute_activity(
                fetch_review_context,
                input,
                start_to_close_timeout=FETCH_CONTEXT_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

            # Wait out in-flight reviewer bots (fresh trusted-bot 👀) before provisioning: the
            # sandbox holds no token to poll GitHub with, so the Action's wait-and-poll lives here
            # as durable timers. Each poll refreshes the stored reactions snapshot; if the budget
            # expires with a bot still in flight, the run proceeds and the engine sees the fresh 👀
            # and returns WAIT rather than approving over an unfinished review.
            for _ in range(STAMPHOG_BOT_REVIEW_MAX_POLLS):
                bots = await workflow.execute_activity(
                    list_in_flight_reviewer_bots,
                    input,
                    start_to_close_timeout=FETCH_CONTEXT_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                if not bots["in_flight"]:
                    break
                await asyncio.sleep(STAMPHOG_BOT_REVIEW_POLL_SECONDS)

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
            # Log the full error to the worker before marking the run failed: mark_review_failed
            # persists only the first line (raw exception text can embed repo file content, and run.error
            # is exposed to stamphog:read), so the worker log is where full detail is kept.
            workflow.logger.error(f"stamphog_review_workflow_failed for run {input.review_run_id}: {e}")
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
