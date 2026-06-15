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

from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.temporal.activities import (
    advance_scanner_watermark_activity,
    count_in_flight_applies_activity,
    find_scanner_candidates_activity,
)
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_WORKFLOW_NAME,
    COUNT_IN_FLIGHT_APPLIES_TIMEOUT,
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    SWEEP_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
)
from products.replay_vision.backend.temporal.sweep_types import (
    AdvanceScannerWatermarkInputs,
    CandidateSessionPayload,
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
        # Hard per-scanner concurrency cap: don't fetch more than the in-flight headroom, and skip entirely
        # when saturated. Keeps one bad config from flooding the shared rasterizer + provider concurrency.
        # The activity fails open (returns 0 on any error), so there's nothing to retry.
        in_flight = await wf.execute_activity(
            count_in_flight_applies_activity,
            CountInFlightAppliesInputs(scanner_id=inputs.scanner_id),
            start_to_close_timeout=COUNT_IN_FLIGHT_APPLIES_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
        headroom = MAX_IN_FLIGHT_APPLIES_PER_SCANNER - in_flight
        if headroom <= 0:
            # At the cap — drain before fetching more. Don't advance the watermark; resume next tick.
            wf.logger.info("replay_vision.sweep_throttled", extra={"scanner_id": str(inputs.scanner_id)})
            return

        find_result = await wf.execute_activity(
            find_scanner_candidates_activity,
            FindScannerCandidatesInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id, candidate_limit=headroom),
            start_to_close_timeout=dt.timedelta(seconds=200),
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
        if not find_result.candidates:
            return

        # First failure aborts the gather and skips the advance; UNIQUE(scanner_id, session_id) dedups retries.
        await asyncio.gather(*(self._start_child(inputs, c) for c in find_result.candidates))

        last = find_result.candidates[-1]
        await wf.execute_activity(
            advance_scanner_watermark_activity,
            AdvanceScannerWatermarkInputs(
                scanner_id=inputs.scanner_id,
                new_last_swept_at=last.session_end,
                new_last_seen_session_id=last.session_id if find_result.saturated else "",
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )

    async def _start_child(self, inputs: SweepScannerInputs, candidate: CandidateSessionPayload) -> None:
        try:
            await wf.start_child_workflow(
                APPLY_SCANNER_WORKFLOW_NAME,
                ApplyScannerInputs(
                    scanner_id=inputs.scanner_id,
                    session_id=candidate.session_id,
                    team_id=inputs.team_id,
                    triggered_by=ObservationTrigger.SCHEDULE,
                ),
                id=build_apply_scanner_workflow_id(inputs.scanner_id, candidate.session_id),
                task_queue=settings.REPLAY_VISION_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                parent_close_policy=wf.ParentClosePolicy.ABANDON,
                # Matches the on-demand /observe/ ceiling.
                execution_timeout=dt.timedelta(hours=1),
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
