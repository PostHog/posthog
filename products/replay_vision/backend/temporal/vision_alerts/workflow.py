"""Temporal workflow for replay vision alert checking."""

import asyncio

import temporalio
from temporalio import workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

# Activities and their payloads sit behind Django imports, which Temporal's workflow
# sandbox blocks; they are only passed as references to execute_activity.
with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.vision_alerts.activities import (
        CheckVisionAlertsInput,
        CheckVisionAlertsOutput,
        CleanupAlertHistoryInput,
        DiscoverDueAlertsInput,
        DiscoverDueAlertsOutput,
        DrainMatchesInput,
        EvaluateAlertBatchInput,
        EvaluateAlertBatchOutput,
        cleanup_vision_alert_history_activity,
        discover_due_vision_alerts_activity,
        drain_vision_alert_matches_activity,
        evaluate_vision_alert_batch_activity,
    )

from products.replay_vision.backend.temporal.vision_alerts.constants import (
    ACTIVITY_RETRY_POLICY,
    ACTIVITY_TIMEOUT,
    WORKFLOW_NAME,
)


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class VisionAlertCheckWorkflow(PostHogWorkflow):
    """Discover due metric alerts, then evaluate batches in parallel."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CheckVisionAlertsInput:
        return CheckVisionAlertsInput()

    @temporalio.workflow.run
    async def run(self, input: CheckVisionAlertsInput) -> CheckVisionAlertsOutput:
        discovery: DiscoverDueAlertsOutput = await workflow.execute_activity(
            discover_due_vision_alerts_activity,
            DiscoverDueAlertsInput(),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        output = CheckVisionAlertsOutput()
        if discovery.batches:
            # return_exceptions=True isolates per-batch retry exhaustion: one batch's
            # failure doesn't abort the cycle.
            results: list[EvaluateAlertBatchOutput | BaseException] = await asyncio.gather(
                *(
                    workflow.execute_activity(
                        evaluate_vision_alert_batch_activity,
                        EvaluateAlertBatchInput(alert_ids=batch),
                        start_to_close_timeout=ACTIVITY_TIMEOUT,
                        retry_policy=ACTIVITY_RETRY_POLICY,
                    )
                    for batch in discovery.batches
                ),
                return_exceptions=True,
            )

            for batch, result in zip(discovery.batches, results):
                if isinstance(result, ActivityError):
                    workflow.logger.warning(
                        "Vision alert batch failed; counting its alerts as errored", batch_size=len(batch)
                    )
                    output.alerts_errored += len(batch)
                elif isinstance(result, BaseException):
                    raise result
                else:
                    output.alerts_checked += result.alerts_checked
                    output.alerts_fired += result.alerts_fired
                    output.alerts_resolved += result.alerts_resolved
                    output.alerts_errored += result.alerts_errored

        # Patched: added after the workflow first shipped; pre-patch histories skip it.
        if workflow.patched("vision-alert-match-drain-2026-08"):
            try:
                await workflow.execute_activity(
                    drain_vision_alert_matches_activity,
                    DrainMatchesInput(),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
            except ActivityError:
                workflow.logger.warning("Match drain failed; alert cycle continues")

        # Best-effort retention sweep; never fails the alert cycle.
        try:
            await workflow.execute_activity(
                cleanup_vision_alert_history_activity,
                CleanupAlertHistoryInput(),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
        except ActivityError:
            workflow.logger.warning("Vision alert history cleanup failed; alert cycle continues")

        return output
