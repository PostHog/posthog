"""Vision-action engine workflows: schedule fan-out and per-action processing."""

import asyncio
import datetime as dt
from typing import TYPE_CHECKING

import temporalio.workflow as wf
from temporalio import common
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.vision_actions.types import (
    CreateVisionActionRunInputs,
    EmitActionReadyInputs,
    ProcessVisionActionInputs,
    ScheduleAllVisionActionsInputs,
    SynthesisStatus,
    SynthesizeActionInputs,
    UpdateVisionActionRunInputs,
)

# `activities` + the synthesis activity pull in Django/ee, which the workflow sandbox can't re-import.
with wf.unsafe.imports_passed_through():
    from products.replay_vision.backend.models.vision_action import VisionActionRunStatus
    from products.replay_vision.backend.temporal.vision_actions.activities import (
        advance_next_run_at_activity,
        create_vision_action_run_activity,
        emit_action_ready_activity,
        fetch_due_vision_actions_activity,
        update_vision_action_run_activity,
        validate_vision_action_activity,
    )
    from products.replay_vision.backend.temporal.vision_actions.synthesis import synthesize_action_activity

if TYPE_CHECKING:
    from temporalio.client import Client

SCHEDULE_ALL_WORKFLOW_NAME = "schedule-all-vision-actions"
PROCESS_WORKFLOW_NAME = "process-vision-action"
SCHEDULE_ID = "replay-vision-actions-schedule"
SCHEDULE_WORKFLOW_ID = "replay-vision-actions"
SCHEDULE_INTERVAL = dt.timedelta(minutes=5)
SCHEDULE_EXECUTION_TIMEOUT = dt.timedelta(minutes=30)
_PROCESS_EXECUTION_TIMEOUT = dt.timedelta(hours=1)

_FETCH_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=10), maximum_interval=dt.timedelta(minutes=5), maximum_attempts=3
)
_RECORD_RETRY = common.RetryPolicy(initial_interval=dt.timedelta(seconds=5), maximum_attempts=3)
_SYNTH_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=30), maximum_interval=dt.timedelta(minutes=5), maximum_attempts=3
)
_EMIT_RETRY = common.RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3)


@wf.defn(name=SCHEDULE_ALL_WORKFLOW_NAME)
class ScheduleAllVisionActionsWorkflow(PostHogWorkflow):
    """Parent fan-out: find due schedule actions and start one child per action."""

    inputs_cls = ScheduleAllVisionActionsInputs
    inputs_optional = True

    @wf.run
    async def run(self, inputs: ScheduleAllVisionActionsInputs) -> None:
        due = await wf.execute_activity(
            fetch_due_vision_actions_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=_FETCH_RETRY,
        )
        if not due:
            return

        tasks = [
            wf.execute_child_workflow(
                ProcessVisionActionWorkflow.run,
                ProcessVisionActionInputs(
                    vision_action_id=d.vision_action_id, team_id=d.team_id, scheduled_at=d.scheduled_at
                ),
                # Deterministic id dedups overlapping ticks: a still-running action is skipped, not double-fired.
                id=f"process-vision-action-{d.vision_action_id}",
                parent_close_policy=wf.ParentClosePolicy.ABANDON,
                execution_timeout=_PROCESS_EXECUTION_TIMEOUT,
            )
            for d in due
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        failed: list[str] = []
        for d, result in zip(due, results):
            if isinstance(result, BaseException):
                if isinstance(result, WorkflowAlreadyStartedError):
                    wf.logger.info("vision_action.already_running", vision_action_id=str(d.vision_action_id))
                else:
                    failed.append(str(d.vision_action_id))
        if failed:
            raise ApplicationError(f"Vision action deliveries failed for: {failed}", non_retryable=True)


@wf.defn(name=PROCESS_WORKFLOW_NAME)
class ProcessVisionActionWorkflow(PostHogWorkflow):
    """Per-action: create run → validate → synthesize → emit, always updating the run and advancing the schedule."""

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
                inputs.vision_action_id,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=_RECORD_RETRY,
            )
            if skip_reason is not None:
                return  # final_status stays SKIPPED (the initialized default)

            synth = await wf.execute_activity(
                synthesize_action_activity,
                SynthesizeActionInputs(run_id=run_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=_SYNTH_RETRY,
            )
            if synth.status in (SynthesisStatus.ABORTED_NO_CONSENT, SynthesisStatus.ABORTED_NO_USER):
                final_status = VisionActionRunStatus.FAILED.value
                return
            if synth.status in (SynthesisStatus.SKIPPED_EMPTY, SynthesisStatus.SKIPPED_OVER_BUDGET):
                return  # final_status stays SKIPPED (the initialized default)

            await wf.execute_activity(
                emit_action_ready_activity,
                EmitActionReadyInputs(run_id=run_id),
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
                        UpdateVisionActionRunInputs(run_id=run_id, status=final_status, error=error_info),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=_RECORD_RETRY,
                    )
                except Exception:
                    wf.logger.exception(
                        "vision_action.update_run_failed", vision_action_id=str(inputs.vision_action_id)
                    )
                    if caught is None:
                        raise
            # Always advance — even a failed run must not hot-loop on the same next_run_at.
            try:
                await wf.execute_activity(
                    advance_next_run_at_activity,
                    inputs.vision_action_id,
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=_RECORD_RETRY,
                )
            except Exception:
                # Must not overwrite a caught error from the body — re-raise only if there was none.
                wf.logger.exception("vision_action.advance_failed", vision_action_id=str(inputs.vision_action_id))
                if caught is None:
                    raise

        # Re-raise after finally — Temporal blocks activity scheduling while an exception propagates.
        if caught:
            raise caught


async def create_replay_vision_actions_schedule(client: "Client") -> None:
    """Upsert the global vision-actions fan-out schedule. Called from worker startup."""
    # Function-local: this module holds `@wf.defn`, and the sandbox can't re-import the schedule
    # helper's Django/temporalio.client dependencies when validating the workflow.
    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=SCHEDULE_ID,
        workflow_name=SCHEDULE_ALL_WORKFLOW_NAME,
        workflow_id=SCHEDULE_WORKFLOW_ID,
        inputs=ScheduleAllVisionActionsInputs(),
        interval=SCHEDULE_INTERVAL,
        execution_timeout=SCHEDULE_EXECUTION_TIMEOUT,
    )
