import asyncio
import functools
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
    from products.experiments.backend.temporal.scheduled_recalculation_logic import (
        SKIP_DISPATCH_UNCERTAIN,
        SKIP_START_WINDOW_ELAPSED,
        ScheduledRecalculationDiscovery,
    )

MAX_CONCURRENT_EXPERIMENTS = 10
SCHEDULED_CALC_BUDGET = 6
SCHEDULED_RUN_CAP = 3

SCHEDULE_INTERVAL = timedelta(hours=1)
START_ACTIVITY_TIMEOUT = timedelta(minutes=2)
START_ACTIVITY_MAX_ATTEMPTS = 2
RUN_WAIT_TIMEOUT = timedelta(minutes=30)
RUN_START_WINDOW = timedelta(minutes=20)

WAIT_FOR_RUNS_PATCH = "scheduled-recalc-wait-for-runs-2026-10"
CALC_BUDGET_PATCH = "scheduled-recalc-calc-budget-2026-11"


@temporalio.workflow.defn(name=SCHEDULED_RECALCULATION_WORKFLOW_NAME)
class ScheduledExperimentRecalculationWorkflow(PostHogWorkflow):
    """Start a real metrics recalculation for every experiment eligible this hour.

    One hourly schedule drives it. Discovery resolves the hour from the clock and selects the
    teams configured for it, so the workflow carries no input and no clock of its own.

    Each started run is an ordinary `ExperimentMetricsRecalculationWorkflow`, dispatched the same
    way the API dispatches one. The workflow waits for a run to finish before it releases that
    run's share of the admission limits: at most SCHEDULED_RUN_CAP runs and SCHEDULED_CALC_BUDGET
    metric calculations in flight, in discovery order. A run with more metrics than the budget
    starts alone. Histories from before CALC_BUDGET_PATCH admit MAX_CONCURRENT_EXPERIMENTS runs.
    Experiments not started within RUN_START_WINDOW are deferred to their next scheduled hour, so
    activity queueing and retries cannot consume the next hourly firing, which SKIP would drop.
    The counts it returns are for an operator reading the run, not a source of truth: each run's
    real outcome lands on its own `ExperimentMetricsRecalculation` row.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> dict[str, int]:
        started_at = temporalio.workflow.now()
        start_before = started_at + RUN_START_WINDOW
        wait_for_runs = temporalio.workflow.patched(WAIT_FOR_RUNS_PATCH)
        calc_budget = temporalio.workflow.patched(CALC_BUDGET_PATCH)
        discovery: ScheduledRecalculationDiscovery = await temporalio.workflow.execute_activity(
            discover_scheduled_recalculation_candidates,
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=RUN_START_WINDOW if wait_for_runs else None,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        hour, candidates = discovery.hour, discovery.candidates

        if not candidates:
            return {"hour": hour, "candidates": 0, "started": 0, "skipped": 0, "deferred": 0}

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXPERIMENTS)
        runs_in_flight = 0
        calcs_in_flight = 0
        deferred = 0
        stop_starting = False

        def _should_defer() -> bool:
            nonlocal deferred
            if wait_for_runs and (stop_starting or temporalio.workflow.now() >= start_before):
                deferred += 1
                return True
            return False

        async def _process(experiment_id: int) -> bool:
            async with semaphore:
                return await _start_and_wait(experiment_id)

        def _has_room_for(weight: int) -> bool:
            return runs_in_flight < SCHEDULED_RUN_CAP and calcs_in_flight + weight <= SCHEDULED_CALC_BUDGET

        async def _run_admitted(experiment_id: int, weight: int) -> bool:
            nonlocal runs_in_flight, calcs_in_flight
            try:
                return await _start_and_wait(experiment_id)
            finally:
                runs_in_flight -= 1
                calcs_in_flight -= weight

        async def _admit_in_discovery_order() -> list[asyncio.Task[bool]]:
            # One waiter at a time, because the SDK checks every waiting condition on each pass and
            # a waiter per candidate makes a large batch quadratic within one workflow task.
            nonlocal runs_in_flight, calcs_in_flight
            admitted: list[asyncio.Task[bool]] = []
            for candidate in candidates:
                weight = (
                    SCHEDULED_CALC_BUDGET
                    if candidate.metric_count is None
                    else min(candidate.metric_count, SCHEDULED_CALC_BUDGET)
                )
                await temporalio.workflow.wait_condition(functools.partial(_has_room_for, weight))
                runs_in_flight += 1
                calcs_in_flight += weight
                admitted.append(asyncio.create_task(_run_admitted(candidate.experiment_id, weight)))
            return admitted

        async def _start_and_wait(experiment_id: int) -> bool:
            nonlocal deferred, stop_starting
            if _should_defer():
                return False
            has_exposures = await temporalio.workflow.execute_activity(
                check_experiment_exposures,
                args=[experiment_id, hour],
                start_to_close_timeout=timedelta(minutes=10),
                schedule_to_close_timeout=(start_before - temporalio.workflow.now()) if wait_for_runs else None,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if not has_exposures or _should_defer():
                return False
            try:
                result = await temporalio.workflow.execute_activity(
                    start_scheduled_recalculation,
                    args=[experiment_id, hour, start_before] if wait_for_runs else [experiment_id, hour],
                    start_to_close_timeout=START_ACTIVITY_TIMEOUT,
                    schedule_to_close_timeout=(
                        min(
                            START_ACTIVITY_TIMEOUT * START_ACTIVITY_MAX_ATTEMPTS,
                            start_before - temporalio.workflow.now(),
                        )
                        if wait_for_runs
                        else None
                    ),
                    retry_policy=RetryPolicy(maximum_attempts=START_ACTIVITY_MAX_ATTEMPTS),
                )
            except ActivityError:
                stop_starting = True
                raise
            if not result.started:
                if result.skip_reason == SKIP_START_WINDOW_ELAPSED:
                    deferred += 1
                elif result.skip_reason == SKIP_DISPATCH_UNCERTAIN:
                    stop_starting = True
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
                    stop_starting = True
                    temporalio.workflow.logger.warning(
                        f"scheduled recalculation {result.recalculation_id} wait ended before the run finished"
                    )
            return True

        if calc_budget:
            outcomes = await asyncio.gather(*await _admit_in_discovery_order(), return_exceptions=True)
        else:
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
