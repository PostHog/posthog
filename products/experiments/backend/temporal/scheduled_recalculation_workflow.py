import asyncio
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.experiments.backend.temporal.models import SCHEDULED_RECALCULATION_WORKFLOW_NAME
    from products.experiments.backend.temporal.scheduled_recalculation_activities import (
        check_experiment_exposures,
        discover_scheduled_recalculation_candidates,
        start_scheduled_recalculation,
    )
    from products.experiments.backend.temporal.scheduled_recalculation_logic import ScheduledRecalculationDiscovery

# Matches the daily timeseries workflows. Each unit here is one cheap query plus one workflow
# start, so this bounds the exposure queries rather than the recalculations themselves.
MAX_CONCURRENT_EXPERIMENTS = 10


@temporalio.workflow.defn(name=SCHEDULED_RECALCULATION_WORKFLOW_NAME)
class ScheduledExperimentRecalculationWorkflow(PostHogWorkflow):
    """Start a real metrics recalculation for every experiment eligible this hour.

    One hourly schedule drives it. Discovery resolves the hour from the clock and selects the
    teams configured for it, so the workflow carries no input and no clock of its own.

    Fire and forget. Each started run is an ordinary `ExperimentMetricsRecalculationWorkflow`,
    dispatched the same way the API dispatches one, and this workflow never waits for it. The
    counts it returns are for an operator reading the run, not a source of truth: each run's
    real outcome lands on its own `ExperimentMetricsRecalculation` row.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> dict[str, int]:
        discovery: ScheduledRecalculationDiscovery = await temporalio.workflow.execute_activity(
            discover_scheduled_recalculation_candidates,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        hour, candidates = discovery.hour, discovery.candidates

        if not candidates:
            return {"hour": hour, "candidates": 0, "started": 0, "skipped": 0}

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXPERIMENTS)

        async def _process(experiment_id: int) -> bool:
            async with semaphore:
                has_exposures = await temporalio.workflow.execute_activity(
                    check_experiment_exposures,
                    args=[experiment_id, hour],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                if not has_exposures:
                    return False
                result = await temporalio.workflow.execute_activity(
                    start_scheduled_recalculation,
                    args=[experiment_id, hour],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                return bool(result.started)

        outcomes = await asyncio.gather(
            *[_process(candidate.experiment_id) for candidate in candidates], return_exceptions=True
        )
        started = sum(1 for outcome in outcomes if outcome is True)

        temporalio.workflow.logger.info(f"scheduled recalculation hour {hour}: {started} of {len(candidates)} started")
        return {
            "hour": hour,
            "candidates": len(candidates),
            "started": started,
            "skipped": len(candidates) - started,
        }
