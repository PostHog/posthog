import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.web_analytics.backend.tasks.heatmap_screenshot import HEATMAP_SCREENSHOT_TIME_LIMIT
    from products.web_analytics.backend.temporal.page_history.activities import (
        claim_capture,
        finish_capture,
        prune_page_history,
        render_capture,
        schedule_page_history,
    )
    from products.web_analytics.backend.temporal.page_history.types import (
        CAPTURE_WORKFLOW_NAME,
        RENDER_ATTEMPTS,
        RENDER_RETRY_DELAY,
        TICK_WORKFLOW_NAME,
        CaptureInputs,
        ClaimedCapture,
        FinishInputs,
        RenderOutcome,
        TickInputs,
        TickResult,
        capture_workflow_id,
    )

DATABASE_TIMEOUT = timedelta(minutes=2)
DATABASE_RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), maximum_attempts=3)


@workflow.defn(name=CAPTURE_WORKFLOW_NAME)
class HeatmapPageHistoryCaptureWorkflow(PostHogWorkflow):
    inputs_cls = CaptureInputs

    @workflow.run
    async def run(self, inputs: CaptureInputs) -> str:
        claim_id = await workflow.execute_activity(
            claim_capture, inputs, start_to_close_timeout=DATABASE_TIMEOUT, retry_policy=DATABASE_RETRY
        )
        if claim_id is None:
            return "skipped"
        capture = ClaimedCapture(team_id=inputs.team_id, request_id=inputs.request_id, claim_id=claim_id)
        try:
            outcome = await workflow.execute_activity(
                render_capture,
                capture,
                start_to_close_timeout=timedelta(seconds=HEATMAP_SCREENSHOT_TIME_LIMIT),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=RENDER_RETRY_DELAY, backoff_coefficient=1.0, maximum_attempts=RENDER_ATTEMPTS
                ),
            )
        except ActivityError:
            outcome = RenderOutcome(failure_cause="render_timeout")
        await workflow.execute_activity(
            finish_capture,
            FinishInputs(capture=capture, outcome=outcome),
            start_to_close_timeout=DATABASE_TIMEOUT,
            retry_policy=DATABASE_RETRY,
        )
        return "succeeded" if outcome.failure_cause is None else "failed"


@workflow.defn(name=TICK_WORKFLOW_NAME)
class HeatmapPageHistoryTickWorkflow(PostHogWorkflow):
    inputs_cls = TickInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: TickInputs) -> TickResult:
        pruned = await workflow.execute_activity(
            prune_page_history, start_to_close_timeout=DATABASE_TIMEOUT, retry_policy=DATABASE_RETRY
        )
        due = await workflow.execute_activity(
            schedule_page_history,
            start_to_close_timeout=DATABASE_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        starts = [
            workflow.start_child_workflow(
                HeatmapPageHistoryCaptureWorkflow.run,
                CaptureInputs(team_id=capture.team_id, request_id=capture.request_id),
                id=capture_workflow_id(capture.request_id),
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                execution_timeout=timedelta(seconds=capture.seconds_left),
            )
            for capture in due
            if capture.seconds_left > 0
        ]
        results = await asyncio.gather(*starts, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, WorkflowAlreadyStartedError):
                raise result
        already_running = sum(isinstance(result, WorkflowAlreadyStartedError) for result in results)
        return TickResult(pruned=pruned, started=len(results) - already_running, already_running=already_running)
