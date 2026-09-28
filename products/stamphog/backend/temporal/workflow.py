"""Stamphog review workflow.

Orchestrates a single PR review: fetch context -> run the engine's gates on the worker and refuse
right away when they alone decide the verdict -> otherwise run the whole engine (gates, tier,
familiarity, LLM review) offline in a sandbox -> post the verdict. Both gate runs are the engine's own
code and surface through the same verdict output. Any unrecoverable error marks the ``ReviewRun``
FAILED. The workflow only moves small inputs between activities (the run id, and a sandbox id and
merge base for the sandbox steps); all bulky data lives on ``ReviewRun.output`` in Postgres.
"""

from __future__ import annotations

import asyncio

import temporalio.workflow
from temporalio import workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import describe_failure

from products.stamphog.backend.temporal.constants import (
    ACTIVITY_RETRY_POLICY,
    FETCH_CONTEXT_TIMEOUT,
    MARK_FAILED_TIMEOUT,
    POST_VERDICT_TIMEOUT,
    PRE_GATES_TIMEOUT,
    RUN_REVIEW_TIMEOUT,
    SANDBOX_CHECKOUT_TIMEOUT,
    SANDBOX_DESTROY_TIMEOUT,
    SANDBOX_RETRY_POLICY,
    SANDBOX_START_TIMEOUT,
    STAMPHOG_BOT_REVIEW_MAX_POLLS,
    STAMPHOG_BOT_REVIEW_POLL_SECONDS,
)

with temporalio.workflow.unsafe.imports_passed_through():
    from products.stamphog.backend.temporal.activities import (
        MarkReviewFailedInput,
        ReviewSandboxInput,
        StamphogReviewInput,
        checkout_review_sandbox,
        destroy_review_sandbox,
        dismiss_stale_approvals,
        fetch_review_context,
        list_in_flight_reviewer_bots,
        mark_review_failed,
        post_verdict,
        refuse_on_pre_gates,
        review_in_sandbox,
        run_review_in_sandbox,
        signal_review_started,
        start_review_sandbox,
    )


@workflow.defn(name="stamphog-review")
class StamphogReviewWorkflow(PostHogWorkflow):
    inputs_cls = StamphogReviewInput

    @workflow.run
    async def run(self, input: StamphogReviewInput) -> dict:
        sandbox_start: asyncio.Future[dict] | None = None
        sandbox_checkout: asyncio.Future[ReviewSandboxInput | None] | None = None
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

            # New command added after this workflow's initial rollout — gated so in-flight executions
            # replaying their recorded history (which never saw this activity) don't hit a
            # Non-Deterministic Error. The moment this run commits to reviewing (right after the stale
            # approval sweep) is also the moment it should show a "review in flight" 👀 on the PR.
            if workflow.patched("stamphog-eyes-reaction"):
                await workflow.execute_activity(
                    signal_review_started,
                    input,
                    start_to_close_timeout=POST_VERDICT_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )

            # The sandbox and the PR head fetch need nothing the next steps produce, so they start now
            # and run beside the context fetch. The checkout starts once the context holds the merge
            # base, and runs beside the pre-check and the bot wait. The workflow does every wait
            # between them: an activity that waited for another activity would hold a worker thread
            # the other one could need. Gated for replay like the eyes reaction above.
            if workflow.patched("stamphog-overlap-sandbox"):
                sandbox_start = asyncio.ensure_future(
                    workflow.execute_activity(
                        start_review_sandbox,
                        input,
                        start_to_close_timeout=SANDBOX_START_TIMEOUT,
                        retry_policy=SANDBOX_RETRY_POLICY,
                    )
                )

            await workflow.execute_activity(
                fetch_review_context,
                input,
                start_to_close_timeout=FETCH_CONTEXT_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

            if sandbox_start is not None:
                sandbox_checkout = asyncio.ensure_future(self._check_out_sandbox(input, sandbox_start))

            # A PR that fails a deterministic gate is refused whatever the reviewer says, so the
            # engine's own gates run here first on the stored context. A final gate verdict (a deny,
            # or the WAIT for a pending migration check) is persisted in the sandbox's output shape,
            # and the run skips the bot wait and the sandbox. Gated for replay like the eyes reaction
            # above.
            refused_on_pre_gates = False
            if workflow.patched("stamphog-pre-gates"):
                try:
                    pre_gates = await workflow.execute_activity(
                        refuse_on_pre_gates,
                        input,
                        start_to_close_timeout=PRE_GATES_TIMEOUT,
                        retry_policy=ACTIVITY_RETRY_POLICY,
                    )
                    refused_on_pre_gates = bool(pre_gates["refused"])
                except ActivityError:
                    # The pre-check is only a shortcut. A timeout or a lost worker falls through to
                    # the full review rather than failing the run.
                    workflow.logger.warning(f"stamphog pre-gates failed for run {input.review_run_id}")

            if not refused_on_pre_gates:
                # Wait out in-flight reviewer bots (fresh trusted-bot 👀) before the review: the
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

                if sandbox_checkout is None:
                    await workflow.execute_activity(
                        run_review_in_sandbox,
                        input,
                        start_to_close_timeout=RUN_REVIEW_TIMEOUT,
                        retry_policy=SANDBOX_RETRY_POLICY,
                    )
                elif (checked_out := await sandbox_checkout) is not None:
                    await workflow.execute_activity(
                        review_in_sandbox,
                        checked_out,
                        start_to_close_timeout=RUN_REVIEW_TIMEOUT,
                        retry_policy=SANDBOX_RETRY_POLICY,
                    )

            result = await workflow.execute_activity(
                post_verdict,
                input,
                start_to_close_timeout=POST_VERDICT_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            if refused_on_pre_gates and sandbox_start is not None:
                # After the verdict, so a pre-check verdict posts without waiting for the clone.
                await self._discard_sandbox(input, sandbox_start, sandbox_checkout)
            return {"status": "completed", "verdict": result["verdict"]}
        except Exception as e:
            # Log the full error to the worker before marking the run failed: mark_review_failed
            # persists only the first line (raw exception text can embed repo file content, and run.error
            # is exposed to stamphog:read), so the worker log is where full detail is kept.
            workflow.logger.error(f"stamphog_review_workflow_failed for run {input.review_run_id}: {e}")
            try:
                await workflow.execute_activity(
                    mark_review_failed,
                    MarkReviewFailedInput(
                        review_run_id=input.review_run_id,
                        team_id=input.team_id,
                        error=describe_failure(e),
                    ),
                    start_to_close_timeout=MARK_FAILED_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
            finally:
                if sandbox_start is not None:
                    await self._discard_sandbox(input, sandbox_start, sandbox_checkout)
            raise

    async def _check_out_sandbox(
        self, input: StamphogReviewInput, sandbox_start: asyncio.Future[dict]
    ) -> ReviewSandboxInput | None:
        """Check out the PR in the started sandbox. None when the start skipped a superseded run."""
        started = await sandbox_start
        sandbox_id = started.get("sandbox_id")
        if not sandbox_id:
            return None
        sandbox = ReviewSandboxInput(review_run_id=input.review_run_id, team_id=input.team_id, sandbox_id=sandbox_id)
        checkout = await workflow.execute_activity(
            checkout_review_sandbox,
            sandbox,
            start_to_close_timeout=SANDBOX_CHECKOUT_TIMEOUT,
            retry_policy=SANDBOX_RETRY_POLICY,
        )
        return ReviewSandboxInput(
            review_run_id=input.review_run_id,
            team_id=input.team_id,
            sandbox_id=sandbox_id,
            merge_base_sha=checkout["merge_base_sha"],
        )

    async def _discard_sandbox(self, input: StamphogReviewInput, *steps: asyncio.Future | None) -> None:
        """Tear down a sandbox no review will use. Never raises: the run already has its outcome.

        Waits for the start and the checkout first, so the teardown finds the sandbox they made
        rather than racing a provision that is still in flight.
        """
        for step in steps:
            if step is None:
                continue
            try:
                await step
            except Exception:
                pass
        try:
            await workflow.execute_activity(
                destroy_review_sandbox,
                input,
                start_to_close_timeout=SANDBOX_DESTROY_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
        except ActivityError:
            workflow.logger.warning(f"stamphog could not tear down the sandbox for run {input.review_run_id}")
