"""Per-scanner sweep: query candidates, dispatch ABANDONed apply-scanner children, advance watermark."""

import asyncio
import datetime as dt

import temporalio.workflow as wf
from temporalio import common
from temporalio.common import SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import (
    POSTHOG_SCANNER_ID_KEY,
    POSTHOG_SESSION_RECORDING_ID_KEY,
    POSTHOG_TEAM_ID_KEY,
)

with wf.unsafe.imports_passed_through():
    from django.conf import settings

    from products.replay_vision.backend.temporal.metrics import record_sweep_outcome

from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.temporal.activities import (
    advance_scanner_watermark_activity,
    check_scanner_budget_activity,
    count_in_flight_by_team_activity,
    find_scanner_candidates_activity,
    sweep_scanner_tick_activity,
)
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_EXECUTION_TIMEOUT,
    APPLY_SCANNER_WORKFLOW_NAME,
    CHECK_SCANNER_BUDGET_TIMEOUT,
    COUNT_IN_FLIGHT_APPLIES_TIMEOUT,
    FIND_SCANNER_CANDIDATES_TIMEOUT,
    SWEEP_SCANNER_TICK_SCHEDULE_TO_CLOSE,
    SWEEP_SCANNER_TICK_TIMEOUT,
    SWEEP_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
    in_flight_headroom,
)
from products.replay_vision.backend.temporal.sweep_types import (
    CandidateSessionPayload,
    CheckScannerBudgetInputs,
    CountInFlightAppliesInputs,
    FindScannerCandidatesInputs,
    FindScannerCandidatesOutput,
    SweepScannerInputs,
    watermark_advance,
)
from products.replay_vision.backend.temporal.types import ApplyScannerInputs

# Gates the single-activity tick. Histories recorded before it keep the four-activity sequence in
# `_run_legacy`, which can be deleted once no sweep started before this patch is still running.
SWEEP_SINGLE_ACTIVITY_PATCH = "replay-vision-sweep-single-activity-2026-11"

# Retries target fast ClickHouse admission rejections (code 202). The waits are long enough for a
# burst to drain, so retries do not take the slots that free up first from API queries.
_FIND_RETRY_POLICY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=dt.timedelta(seconds=120),
    maximum_attempts=3,
)


@wf.defn(name=SWEEP_SCANNER_WORKFLOW_NAME)
class SweepScannerWorkflow(PostHogWorkflow):
    inputs_cls = SweepScannerInputs

    @wf.run
    async def run(self, inputs: SweepScannerInputs) -> None:
        if wf.patched(SWEEP_SINGLE_ACTIVITY_PATCH):
            tick = await wf.execute_activity(
                sweep_scanner_tick_activity,
                inputs,
                start_to_close_timeout=SWEEP_SCANNER_TICK_TIMEOUT,
                schedule_to_close_timeout=SWEEP_SCANNER_TICK_SCHEDULE_TO_CLOSE,
                retry_policy=_FIND_RETRY_POLICY,
            )
            if tick.dispatch is not None:
                await self._dispatch_and_advance(inputs, tick.dispatch)
            return

        await self._run_legacy(inputs)

    async def _run_legacy(self, inputs: SweepScannerInputs) -> None:
        # A capped scanner scans no sessions this tick. Fails open because admissions stay gated at the
        # persistence boundary.
        try:
            budget = await wf.execute_activity(
                check_scanner_budget_activity,
                CheckScannerBudgetInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id),
                start_to_close_timeout=CHECK_SCANNER_BUDGET_TIMEOUT,
                retry_policy=common.RetryPolicy(maximum_attempts=1),
            )
            if budget.capped:
                return
        except Exception:
            if not wf.unsafe.is_replaying():
                record_sweep_outcome("scanner_budget_check_failed")
            wf.logger.warning("replay_vision.scanner_budget_check_failed", extra={"scanner_id": str(inputs.scanner_id)})

        # Hard concurrency caps: per scanner (one bad config) and per team (many scanners), enforced as the
        # min of the two headrooms. Skip entirely when saturated. Keeps any single tenant from flooding the
        # shared rasterizer + provider concurrency. A DB error fails the count (single attempt), so the sweep
        # skips this tick rather than dispatching against an unknown load; the next tick retries in 5 minutes.
        in_flight = await wf.execute_activity(
            count_in_flight_by_team_activity,
            CountInFlightAppliesInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id),
            start_to_close_timeout=COUNT_IN_FLIGHT_APPLIES_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
        scanner_in_flight, team_in_flight = in_flight.scanner, in_flight.team
        headroom = in_flight_headroom(scanner_in_flight, team_in_flight)
        if headroom <= 0:
            # At a cap — drain before fetching more. Don't advance the watermark; resume next tick.
            wf.logger.info(
                "replay_vision.sweep_throttled",
                extra={
                    "scanner_id": str(inputs.scanner_id),
                    "scanner_in_flight": scanner_in_flight,
                    "team_in_flight": team_in_flight,
                },
            )
            return

        # Retries target fast ClickHouse admission rejections (code 202). The waits are long enough for a
        # burst to drain, so retries do not take the slots that free up first from API queries. The next
        # tick starts in 5 minutes and the watermark stays put, so a failed tick loses nothing.
        # schedule_to_close deliberately cuts slow timeout-bound attempts off after two rounds so the tick
        # fails with ~10 minutes of the 15-minute workflow budget left, instead of burning it on a query
        # that keeps timing out.
        find_result = await wf.execute_activity(
            find_scanner_candidates_activity,
            FindScannerCandidatesInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id, candidate_limit=headroom),
            start_to_close_timeout=FIND_SCANNER_CANDIDATES_TIMEOUT,
            schedule_to_close_timeout=dt.timedelta(seconds=450),
            retry_policy=_FIND_RETRY_POLICY,
        )
        await self._dispatch_and_advance(inputs, find_result)

    async def _dispatch_and_advance(self, inputs: SweepScannerInputs, find_result: FindScannerCandidatesOutput) -> None:
        # A no-op when both lists are empty. First failure aborts the gather and skips the advance;
        # UNIQUE(scanner_id, session_id) dedups retries. Priming samples everything, so the tick's
        # balanced rates describe only the fast and deep candidates.
        await asyncio.gather(
            *(
                self._start_child(inputs, c, find_result.variant_sampling_rates)
                for c in (*find_result.candidates, *find_result.deep_candidates)
            ),
            *(self._start_child(inputs, c, None) for c in find_result.priming_candidates),
        )

        advance = watermark_advance(inputs.scanner_id, find_result)
        if advance is None:
            return
        await wf.execute_activity(
            advance_scanner_watermark_activity,
            advance,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )

    async def _start_child(
        self,
        inputs: SweepScannerInputs,
        candidate: CandidateSessionPayload,
        variant_sampling_rates: dict[str, float] | None,
    ) -> None:
        try:
            await wf.start_child_workflow(
                APPLY_SCANNER_WORKFLOW_NAME,
                ApplyScannerInputs(
                    scanner_id=inputs.scanner_id,
                    session_id=candidate.session_id,
                    team_id=inputs.team_id,
                    triggered_by=ObservationTrigger.SCHEDULE,
                    variant_sampling_rates=variant_sampling_rates,
                ),
                id=build_apply_scanner_workflow_id(inputs.scanner_id, candidate.session_id),
                task_queue=settings.REPLAY_VISION_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                parent_close_policy=wf.ParentClosePolicy.ABANDON,
                execution_timeout=APPLY_SCANNER_EXECUTION_TIMEOUT,
                search_attributes=TypedSearchAttributes(
                    search_attributes=[
                        SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=inputs.team_id),
                        SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=candidate.session_id),
                        SearchAttributePair(key=POSTHOG_SCANNER_ID_KEY, value=str(inputs.scanner_id)),
                    ]
                ),
            )
        except WorkflowAlreadyStartedError:
            # This (scanner, session) is already running — skip.
            pass
