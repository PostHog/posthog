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
    sweep_scanner_tick_activity,
)
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_EXECUTION_TIMEOUT,
    APPLY_SCANNER_WORKFLOW_NAME,
    SWEEP_SCANNER_TICK_SCHEDULE_TO_CLOSE,
    SWEEP_SCANNER_TICK_TIMEOUT,
    SWEEP_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
)
from products.replay_vision.backend.temporal.sweep_types import (
    CandidateSessionPayload,
    FindScannerCandidatesOutput,
    SweepScannerInputs,
    watermark_advance,
)
from products.replay_vision.backend.temporal.types import ApplyScannerInputs

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
        tick = await wf.execute_activity(
            sweep_scanner_tick_activity,
            inputs,
            start_to_close_timeout=SWEEP_SCANNER_TICK_TIMEOUT,
            schedule_to_close_timeout=SWEEP_SCANNER_TICK_SCHEDULE_TO_CLOSE,
            retry_policy=_FIND_RETRY_POLICY,
        )
        if tick.dispatch is not None:
            await self._dispatch_and_advance(inputs, tick.dispatch)

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
