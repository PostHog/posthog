"""Temporal workflow for metrics alert checking — discover, then fan out per alert."""

import asyncio

import temporalio
from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow

# Activities and constants live behind Django imports; mark as pass-through so the
# workflow sandbox doesn't choke on them (we only reference the callables/values).
with workflow.unsafe.imports_passed_through():
    from products.metrics.backend.temporal.activities import (
        CheckMetricsAlertInput,
        CheckMetricsAlertOutput,
        DiscoverMetricsAlertsInput,
        DiscoverMetricsAlertsOutput,
        check_metrics_alert_activity,
        discover_metrics_alerts_activity,
    )
    from products.metrics.backend.temporal.constants import ACTIVITY_RETRY_POLICY, ACTIVITY_TIMEOUT, WORKFLOW_NAME


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class MetricsAlertCheckWorkflow(PostHogWorkflow):
    """Discover due metrics alerts, then check each in parallel across workers."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DiscoverMetricsAlertsInput:
        return DiscoverMetricsAlertsInput()

    @temporalio.workflow.run
    async def run(self, input: DiscoverMetricsAlertsInput) -> list[CheckMetricsAlertOutput]:
        discovery: DiscoverMetricsAlertsOutput = await workflow.execute_activity(
            discover_metrics_alerts_activity,
            input,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        if not discovery.alerts:
            return []

        results = await asyncio.gather(
            *(
                workflow.execute_activity(
                    check_metrics_alert_activity,
                    CheckMetricsAlertInput(alert_id=a.alert_id, team_id=a.team_id),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                for a in discovery.alerts
            ),
            return_exceptions=True,
        )

        outputs: list[CheckMetricsAlertOutput] = []
        for discovered, result in zip(discovery.alerts, results):
            if isinstance(result, BaseException):
                workflow.logger.warning(
                    "Metrics alert check activity failed",
                    extra={"alert_id": discovered.alert_id, "error": str(result)},
                )
                continue
            outputs.append(result)
        return outputs
