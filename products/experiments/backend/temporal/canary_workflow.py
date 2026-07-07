import json
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.experiments.backend.temporal.canary_activities import (
        report_experiment_canary_results,
        run_experiment_metric_canary,
        sample_experiment_canary_targets,
    )
    from products.experiments.backend.temporal.models import (
        CANARY_WORKFLOW_NAME,
        MAX_CANARY_DETAIL_LENGTH,
        OUTCOME_ERROR,
        OUTCOME_SKIPPED,
        CanaryMetricResult,
        CanaryReportInputs,
        ExperimentPrecomputeCanaryInputs,
    )

# Three sequential queries at the runner's 600s ceiling each, plus headroom.
METRIC_ACTIVITY_TIMEOUT = timedelta(minutes=35)


@temporalio.workflow.defn(name=CANARY_WORKFLOW_NAME)
class ExperimentPrecomputeCanaryWorkflow(PostHogWorkflow):
    """Verify precomputed experiment results against paired reads and a direct events scan.

    Samples metrics across precompute-enabled teams, runs them sequentially (metrics of one experiment
    share its exposures cache, so only the first recomputes it; sequential execution also avoids concurrent
    writes to the lazy-computation job table), and reports outcomes to Prometheus and Slack. See
    ``canary_logic`` for the comparison rules and the runbook.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentPrecomputeCanaryInputs:
        loaded = json.loads(inputs[0]) if inputs else {}
        return ExperimentPrecomputeCanaryInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentPrecomputeCanaryInputs) -> dict:
        start = temporalio.workflow.now()

        targets = await temporalio.workflow.execute_activity(
            sample_experiment_canary_targets,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        results: list[CanaryMetricResult] = []
        budget = timedelta(seconds=inputs.time_budget_seconds)
        for target in targets:
            if temporalio.workflow.now() - start > budget:
                results.append(
                    CanaryMetricResult(target=target, outcome=OUTCOME_SKIPPED, detail="time budget exhausted")
                )
                continue
            try:
                result = await temporalio.workflow.execute_activity(
                    run_experiment_metric_canary,
                    target,
                    # No heartbeat: each of the three runs is one blocking ClickHouse query with no
                    # progress hooks, so start_to_close_timeout is the real per-attempt ceiling.
                    start_to_close_timeout=METRIC_ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(seconds=5),
                        maximum_interval=timedelta(minutes=1),
                    ),
                )
            except Exception as e:
                # Query failures are monitoring signal, not a reason to abandon the remaining metrics.
                result = CanaryMetricResult(
                    target=target, outcome=OUTCOME_ERROR, detail=str(e)[:MAX_CANARY_DETAIL_LENGTH]
                )
            results.append(result)

        await temporalio.workflow.execute_activity(
            report_experiment_canary_results,
            CanaryReportInputs(results=results, triggered_manually=inputs.triggered_manually),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        counts: dict[str, int] = {}
        for result in results:
            counts[result.outcome] = counts.get(result.outcome, 0) + 1
        temporalio.workflow.logger.info(f"experiment precompute canary finished: {counts or 'no targets'}")
        return {"total": len(results), **counts}
