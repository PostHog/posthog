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
    PROCESS_VISION_ACTION_EXECUTION_TIMEOUT,
    PROCESS_VISION_ACTION_WORKFLOW_NAME,
    SWEEP_SCANNER_WORKFLOW_NAME,
    build_apply_scanner_workflow_id,
    build_process_vision_action_workflow_id,
)
from products.replay_vision.backend.temporal.sweep_types import (
    AdvanceScannerWatermarkInputs,
    CandidateSessionPayload,
    CountInFlightAppliesInputs,
    FindScannerCandidatesInputs,
    SweepScannerInputs,
)
from products.replay_vision.backend.temporal.types import ApplyScannerInputs
from products.replay_vision.backend.temporal.vision_actions.activities import evaluate_due_vision_actions_activity
from products.replay_vision.backend.temporal.vision_actions.types import (
    EvaluateDueVisionActionsInputs,
    ProcessVisionActionInputs,
)

_VISION_ACTION_EVAL_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=5), maximum_interval=dt.timedelta(minutes=1), maximum_attempts=3
)


@wf.defn(name=SWEEP_SCANNER_WORKFLOW_NAME)
class SweepScannerWorkflow(PostHogWorkflow):
    inputs_cls = SweepScannerInputs

    @wf.run
    async def run(self, inputs: SweepScannerInputs) -> None:
        # The sweep is also the heartbeat for this scanner's "and then…" vision actions. Run it first
        # and best-effort: a vision-action problem must never block the scanner's core session scan,
        # and it's independent of the in-flight throttle below (which is about apply-scanner load).
        await self._dispatch_due_vision_actions(inputs)

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

    async def _dispatch_due_vision_actions(self, inputs: SweepScannerInputs) -> None:
        """Evaluate this scanner's due vision actions and fire-and-forget one child per action.

        The eligibility activity claims each action (advances next_run_at) in its own transaction, so
        an ABANDONed child that runs slowly or fails can't be re-fired by the next sweep. Wrapped in a
        broad except: the session scan that follows must proceed even if vision-action dispatch fails.
        """
        try:
            due = await wf.execute_activity(
                evaluate_due_vision_actions_activity,
                EvaluateDueVisionActionsInputs(scanner_id=inputs.scanner_id, team_id=inputs.team_id),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=_VISION_ACTION_EVAL_RETRY,
            )
            for d in due:
                try:
                    await wf.start_child_workflow(
                        PROCESS_VISION_ACTION_WORKFLOW_NAME,
                        ProcessVisionActionInputs(
                            vision_action_id=d.vision_action_id, team_id=d.team_id, scheduled_at=d.scheduled_at
                        ),
                        id=build_process_vision_action_workflow_id(d.vision_action_id),
                        task_queue=settings.REPLAY_VISION_TASK_QUEUE,
                        parent_close_policy=wf.ParentClosePolicy.ABANDON,
                        execution_timeout=PROCESS_VISION_ACTION_EXECUTION_TIMEOUT,
                    )
                except WorkflowAlreadyStartedError:
                    wf.logger.info(
                        "replay_vision.vision_action_already_running",
                        extra={"vision_action_id": str(d.vision_action_id)},
                    )
                except Exception:
                    # The action was already claimed (next_run_at advanced in the eval txn), so a child
                    # that fails to start drops this occurrence until the next fire. Log it per-action
                    # so the drop is visible/graphable, and keep dispatching the rest.
                    wf.logger.exception(
                        "replay_vision.vision_action_claim_dispatch_failed",
                        extra={"scanner_id": str(inputs.scanner_id), "vision_action_id": str(d.vision_action_id)},
                    )
        except Exception:
            # The eligibility activity itself failed (exhausted retries); no action was claimed.
            wf.logger.exception(
                "replay_vision.vision_action_dispatch_failed", extra={"scanner_id": str(inputs.scanner_id)}
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
