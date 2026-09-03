"""Per-backfill tick: gate on quota and in-flight caps, dispatch a newest-first batch, advance the cursor."""

import asyncio

from temporalio import (
    common,
    workflow as wf,
)
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
        advance_backfill_cursor_activity,
        delete_backfill_schedule_activity,
        find_backfill_candidates_activity,
        pause_backfill_schedule_activity,
        prepare_backfill_tick_activity,
    )
    from products.replay_vision.backend.temporal.backfill_types import (
        AdvanceBackfillCursorInputs,
        BackfillScheduleOpInputs,
        BackfillTickAction,
        BackfillTickInputs,
        FindBackfillCandidatesInputs,
    )
    from products.replay_vision.backend.temporal.constants import (
        ADVANCE_BACKFILL_CURSOR_TIMEOUT,
        APPLY_SCANNER_EXECUTION_TIMEOUT,
        APPLY_SCANNER_WORKFLOW_NAME,
        BACKFILL_SCANNER_WORKFLOW_NAME,
        BACKFILL_SCHEDULE_OP_TIMEOUT,
        FIND_BACKFILL_CANDIDATES_TIMEOUT,
        PREPARE_BACKFILL_TICK_TIMEOUT,
        build_apply_scanner_workflow_id,
    )
    from products.replay_vision.backend.temporal.sweep_types import CandidateSessionPayload
    from products.replay_vision.backend.temporal.types import ApplyScannerInputs


@wf.defn(name=BACKFILL_SCANNER_WORKFLOW_NAME)
class BackfillScannerWorkflow(PostHogWorkflow):
    inputs_cls = BackfillTickInputs

    @wf.run
    async def run(self, inputs: BackfillTickInputs) -> None:
        prep = await wf.execute_activity(
            prepare_backfill_tick_activity,
            inputs,
            start_to_close_timeout=PREPARE_BACKFILL_TICK_TIMEOUT,
            # A failed gate skips this tick; the next fire retries in a minute.
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
        if prep.action == BackfillTickAction.FINISHED:
            await self._delete_own_schedule(inputs)
            return
        if prep.action == BackfillTickAction.PAUSE:
            await wf.execute_activity(
                pause_backfill_schedule_activity,
                BackfillScheduleOpInputs(backfill_id=inputs.backfill_id),
                start_to_close_timeout=BACKFILL_SCHEDULE_OP_TIMEOUT,
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            return
        if prep.action == BackfillTickAction.SKIP or prep.dispatch_budget <= 0:
            return

        find_result = await wf.execute_activity(
            find_backfill_candidates_activity,
            FindBackfillCandidatesInputs(
                backfill_id=inputs.backfill_id, team_id=inputs.team_id, candidate_limit=prep.dispatch_budget
            ),
            start_to_close_timeout=FIND_BACKFILL_CANDIDATES_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )

        if find_result.candidates:
            # Deterministic child ids collide with live-sweep applies of the same (scanner, session), so
            # a session observed live is skipped here for free.
            await asyncio.gather(*(self._start_child(inputs, c) for c in find_result.candidates))

        # The activity decides how far the walk got, since it can step over sessions that were
        # already observed but must not step over ones the caps held back.
        advance = AdvanceBackfillCursorInputs(
            backfill_id=inputs.backfill_id,
            team_id=inputs.team_id,
            new_cursor_end_time=find_result.next_cursor_end_time,
            new_cursor_session_id=find_result.next_cursor_session_id,
            expected_cursor_end_time=find_result.started_from_cursor_end_time,
            expected_cursor_session_id=find_result.started_from_cursor_session_id,
            dispatched_delta=len(find_result.candidates),
            skipped_delta=find_result.skipped_delta,
            exhausted=not find_result.more_work_below_cursor,
        )

        result = await wf.execute_activity(
            advance_backfill_cursor_activity,
            advance,
            start_to_close_timeout=ADVANCE_BACKFILL_CURSOR_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )
        if result.finished:
            await self._delete_own_schedule(inputs)

    async def _delete_own_schedule(self, inputs: BackfillTickInputs) -> None:
        # Best-effort: the reconciler's backfill reaper deletes stragglers.
        try:
            await wf.execute_activity(
                delete_backfill_schedule_activity,
                BackfillScheduleOpInputs(backfill_id=inputs.backfill_id),
                start_to_close_timeout=BACKFILL_SCHEDULE_OP_TIMEOUT,
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            wf.logger.exception(
                "replay_vision.backfill_schedule_delete_failed", extra={"backfill_id": str(inputs.backfill_id)}
            )

    async def _start_child(self, inputs: BackfillTickInputs, candidate: CandidateSessionPayload) -> None:
        try:
            await wf.start_child_workflow(
                APPLY_SCANNER_WORKFLOW_NAME,
                ApplyScannerInputs(
                    scanner_id=inputs.scanner_id,
                    session_id=candidate.session_id,
                    team_id=inputs.team_id,
                    triggered_by=ObservationTrigger.BACKFILL,
                    backfill_id=inputs.backfill_id,
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
            pass
