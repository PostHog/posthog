import asyncio
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.experiments.backend.temporal.models import SCHEDULED_RECALCULATION_WORKFLOW_NAME
    from products.experiments.backend.temporal.scheduled_recalculation_activities import (
        check_experiment_exposures,
        discover_scheduled_recalculation_candidates,
        start_scheduled_recalculation,
        wait_for_scheduled_recalculation,
    )
    from products.experiments.backend.temporal.scheduled_recalculation_logic import ScheduledRecalculationDiscovery

MAX_CONCURRENT_EXPERIMENTS = 10

SCHEDULE_INTERVAL = timedelta(hours=1)
START_ACTIVITY_TIMEOUT = timedelta(minutes=2)
START_ACTIVITY_MAX_ATTEMPTS = 2
RUN_WAIT_TIMEOUT = timedelta(minutes=30)
RUN_START_WINDOW = timedelta(minutes=20)

WAIT_FOR_RUNS_PATCH = "scheduled-recalc-wait-for-runs-2026-10"


@temporalio.workflow.defn(name=SCHEDULED_RECALCULATION_WORKFLOW_NAME)
class ScheduledExperimentRecalculationWorkflow(PostHogWorkflow):
    """Start a real metrics recalculation for every experiment eligible this hour.

    One hourly schedule drives it. Discovery resolves the hour from the clock and selects the
    teams configured for it, so the workflow carries no input and no clock of its own.

    Each started run is an ordinary `ExperimentMetricsRecalculationWorkflow`, dispatched the same
    way the API dispatches one. The workflow waits for a run to finish before it uses that slot
    for the next experiment, so at most MAX_CONCURRENT_EXPERIMENTS runs query ClickHouse at once.
    Experiments not started within RUN_START_WINDOW are deferred to their next scheduled hour, so
    the workflow ends before the next hourly firing, which the SKIP overlap policy would drop.
    The counts it returns are for an operator reading the run, not a source of truth: each run's
    real outcome lands on its own `ExperimentMetricsRecalculation` row.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> dict[str, int]:
        started_at = temporalio.workflow.now()
        discovery: ScheduledRecalculationDiscovery = await temporalio.workflow.execute_activity(
            discover_scheduled_recalculation_candidates,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        hour, candidates = discovery.hour, discovery.candidates

        if not candidates:
            return {"hour": hour, "candidates": 0, "started": 0, "skipped": 0, "deferred": 0}

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXPERIMENTS)
        wait_for_runs = temporalio.workflow.patched(WAIT_FOR_RUNS_PATCH)
        deferred = 0

        def _past_start_window() -> bool:
            nonlocal deferred
            if wait_for_runs and temporalio.workflow.now() - started_at > RUN_START_WINDOW:
                deferred += 1
                return True
            return False

        async def _process(experiment_id: int) -> bool:
            async with semaphore:
                if _past_start_window():
                    return False
                has_exposures = await temporalio.workflow.execute_activity(
                    check_experiment_exposures,
                    args=[experiment_id, hour],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                if not has_exposures or _past_start_window():
                    return False
                result = await temporalio.workflow.execute_activity(
                    start_scheduled_recalculation,
                    args=[experiment_id, hour],
                    start_to_close_timeout=START_ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=START_ACTIVITY_MAX_ATTEMPTS),
                )
                if not result.started:
                    return False
                if wait_for_runs and result.recalculation_id is not None:
                    try:
                        await temporalio.workflow.execute_activity(
                            wait_for_scheduled_recalculation,
                            result.recalculation_id,
                            schedule_to_close_timeout=RUN_WAIT_TIMEOUT,
                            heartbeat_timeout=timedelta(minutes=1),
                        )
                    except ActivityError:
                        temporalio.workflow.logger.warning(
                            f"scheduled recalculation {result.recalculation_id} wait ended before the run finished"
                        )
                return True

        outcomes = await asyncio.gather(
            *[_process(candidate.experiment_id) for candidate in candidates], return_exceptions=True
        )
        started = sum(1 for outcome in outcomes if outcome is True)

        temporalio.workflow.logger.info(
            f"scheduled recalculation hour {hour}: {started} of {len(candidates)} started, {deferred} deferred"
        )
        return {
            "hour": hour,
            "candidates": len(candidates),
            "started": started,
            "skipped": len(candidates) - started,
            "deferred": deferred,
        }
