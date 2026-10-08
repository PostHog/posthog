"""Per-scanner sweep: query candidates, dispatch ABANDONed apply-scanner children, advance watermark."""

import asyncio
import datetime as dt
from uuid import UUID

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
)
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_EXECUTION_TIMEOUT,
    APPLY_SCANNER_WORKFLOW_NAME,
    CHECK_SCANNER_BUDGET_TIMEOUT,
    COUNT_IN_FLIGHT_APPLIES_TIMEOUT,
    FIND_SCANNER_CANDIDATES_TIMEOUT,
    SWEEP_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
    in_flight_headroom,
)
from products.replay_vision.backend.temporal.sweep_types import (
    AdvanceScannerWatermarkInputs,
    CandidateSessionPayload,
    CheckScannerBudgetInputs,
    CountInFlightAppliesInputs,
    FindScannerCandidatesInputs,
    SweepScannerInputs,
)
from products.replay_vision.backend.temporal.types import ApplyScannerInputs


@wf.defn(name=SWEEP_SCANNER_WORKFLOW_NAME)
class SweepScannerWorkflow(PostHogWorkflow):
    inputs_cls = SweepScannerInputs

    @wf.run
    async def run(self, inputs: SweepScannerInputs) -> None:
        # A capped scanner scans no sessions this tick. Fails open because admissions stay gated at the
        # persistence boundary.
        wf.deprecate_patch("drop-prompt-suggestion-refresh-2026-10")
        wf.deprecate_patch("replay-vision-scanner-credit-limit")
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
        wf.deprecate_patch("replay-vision-team-in-flight-caps")
        in_flight = await wf.execute_activity(
            count_in_flight_by_team_activity,
            CountInFlightAppliesInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id),
            start_to_close_timeout=COUNT_IN_FLIGHT_APPLIES_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
        scanner_in_flight, team_in_flight = in_flight.scanner, in_flight.team
        wf.deprecate_patch("replay-vision-on-demand-reserved-headroom")
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

        # Retries target fast ClickHouse admission rejections (code 202); schedule_to_close deliberately
        # cuts slow timeout-bound attempts off after two rounds so the tick fails with ~10 minutes of the
        # 15-minute workflow budget left, instead of burning it on a query that keeps timing out.
        find_result = await wf.execute_activity(
            find_scanner_candidates_activity,
            FindScannerCandidatesInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id, candidate_limit=headroom),
            start_to_close_timeout=FIND_SCANNER_CANDIDATES_TIMEOUT,
            schedule_to_close_timeout=dt.timedelta(seconds=450),
            retry_policy=common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                backoff_coefficient=2.0,
                maximum_interval=dt.timedelta(seconds=30),
                maximum_attempts=4,
            ),
        )
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

        if find_result.keyset_end is not None:
            # The fetched batch's last row, which sits ahead of the dispatched candidates whenever
            # exclusion dropped some, so dropping rows cannot stall the walk.
            swept_at = find_result.keyset_end
            # Always carried: the keyset compares the whole tuple, so keeping the tiebreaker cannot
            # skip anything, while dropping it hides any session tied at that exact end_time.
            last_seen_session_id = find_result.keyset_session_id
        elif find_result.swept_through is not None:
            # Advance through the covered settle horizon so `last_swept_at` reflects sweep liveness
            # instead of freezing on low-yield scanners.
            swept_at, last_seen_session_id = find_result.swept_through, ""
        else:
            return

        await self._advance_watermark(
            inputs.scanner_id,
            swept_at,
            last_seen_session_id,
            deep_swept_through=find_result.deep_swept_through,
            deep_keyset_session_id=find_result.deep_keyset_session_id,
        )

    async def _advance_watermark(
        self,
        scanner_id: UUID,
        swept_at: dt.datetime,
        last_seen_session_id: str = "",
        deep_swept_through: dt.datetime | None = None,
        deep_keyset_session_id: str = "",
    ) -> None:
        await wf.execute_activity(
            advance_scanner_watermark_activity,
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner_id,
                new_last_swept_at=swept_at,
                new_last_seen_session_id=last_seen_session_id,
                new_last_deep_swept_at=deep_swept_through,
                new_last_deep_seen_session_id=deep_keyset_session_id,
            ),
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
