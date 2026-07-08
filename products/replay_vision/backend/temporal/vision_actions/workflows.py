"""Vision-action engine: the per-action processing workflow.

The trigger is the per-scanner sweep (`SweepScannerWorkflow`), not a standalone schedule — the
sweep evaluates due actions and fire-and-forgets one of these children per action. The schedule
cursor is advanced at claim time in `evaluate_due_vision_actions_activity`, so this workflow never
touches `next_run_at`.
"""

import datetime as dt

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import PROCESS_VISION_ACTION_WORKFLOW_NAME
from products.replay_vision.backend.temporal.vision_actions.types import (
    CreateVisionActionRunInputs,
    EmitActionReadyInputs,
    ProcessVisionActionInputs,
    SynthesisStatus,
    SynthesizeGroupSummaryInputs,
    UpdateVisionActionRunInputs,
    ValidateVisionActionInputs,
)

# `activities` + the synthesis activity pull in Django/ee, which the workflow sandbox can't re-import.
with wf.unsafe.imports_passed_through():
    from products.replay_vision.backend.models.vision_action import VisionActionRunStatus
    from products.replay_vision.backend.temporal.vision_actions.activities import (
        create_vision_action_run_activity,
        emit_action_ready_activity,
        update_vision_action_run_activity,
        validate_vision_action_activity,
    )
    from products.replay_vision.backend.temporal.vision_actions.synthesis import synthesize_group_summary_activity

_RECORD_RETRY = common.RetryPolicy(initial_interval=dt.timedelta(seconds=5), maximum_attempts=3)
_SYNTH_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=30), maximum_interval=dt.timedelta(minutes=5), maximum_attempts=3
)
_EMIT_RETRY = common.RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3)


@wf.defn(name=PROCESS_VISION_ACTION_WORKFLOW_NAME)
class ProcessVisionActionWorkflow(PostHogWorkflow):
    """Per-action: create run → validate → synthesize → emit, always updating the run at the end."""

    inputs_cls = ProcessVisionActionInputs

    @wf.run
    async def run(self, inputs: ProcessVisionActionInputs) -> None:
        run_id = None
        final_status = VisionActionRunStatus.SKIPPED.value
        error_info: dict | None = None
        caught: BaseException | None = None

        try:
            run_id = await wf.execute_activity(
                create_vision_action_run_activity,
                CreateVisionActionRunInputs(
                    vision_action_id=inputs.vision_action_id,
                    team_id=inputs.team_id,
                    idempotency_key=str(wf.uuid4()),
                    temporal_workflow_id=wf.info().workflow_id,
                    scheduled_at=inputs.scheduled_at,
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=_RECORD_RETRY,
            )

            skip_reason = await wf.execute_activity(
                validate_vision_action_activity,
                ValidateVisionActionInputs(vision_action_id=inputs.vision_action_id, team_id=inputs.team_id),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=_RECORD_RETRY,
            )
            if skip_reason is not None:
                # final_status stays SKIPPED; record why so the run isn't an unexplained skip.
                error_info = {"skip_reason": skip_reason}
                return

            synth = await wf.execute_activity(
                synthesize_group_summary_activity,
                SynthesizeGroupSummaryInputs(run_id=run_id, team_id=inputs.team_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=_SYNTH_RETRY,
            )
            if synth.status in (SynthesisStatus.ABORTED_NO_CONSENT, SynthesisStatus.ABORTED_NO_USER):
                final_status = VisionActionRunStatus.FAILED.value
                error_info = {"aborted": synth.status.value}
                return
            if synth.status in (SynthesisStatus.SKIPPED_EMPTY, SynthesisStatus.SKIPPED_OVER_BUDGET):
                # final_status stays SKIPPED; record why so the run isn't an unexplained skip.
                error_info = {"skip_reason": synth.status.value}
                return

            await wf.execute_activity(
                emit_action_ready_activity,
                EmitActionReadyInputs(run_id=run_id, team_id=inputs.team_id),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=_EMIT_RETRY,
            )
            final_status = VisionActionRunStatus.COMPLETED.value

        except Exception as e:
            caught = e
            final_status = VisionActionRunStatus.FAILED.value
            error_info = {"message": str(e)[:500]}

        finally:
            if run_id is not None:
                try:
                    await wf.execute_activity(
                        update_vision_action_run_activity,
                        UpdateVisionActionRunInputs(
                            run_id=run_id, team_id=inputs.team_id, status=final_status, error=error_info
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=_RECORD_RETRY,
                    )
                except Exception:
                    # If the body already succeeded, the delivery event was emitted (Slack post happened);
                    # a failed bookkeeping update must not flip the workflow to FAILED — re-running would
                    # double-post. Log loudly and let the workflow finish; the run row may stay RUNNING
                    # (cosmetic, a post-MVP reconciler can resolve it). If the body failed, the original
                    # error still re-raises below — the update failure must not mask it.
                    wf.logger.exception(
                        "vision_action.update_run_failed", vision_action_id=str(inputs.vision_action_id)
                    )

        # Re-raise after finally — Temporal blocks activity scheduling while an exception propagates.
        if caught:
            raise caught
