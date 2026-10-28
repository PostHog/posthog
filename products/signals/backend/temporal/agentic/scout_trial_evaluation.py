from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.scout_harness.limits import (
    TRIAL_EVALUATION_TIMEOUT_MINUTES,
    TRIAL_JUDGE_CONCURRENCY,
    TRIAL_JUDGE_TIMEOUT_MINUTES,
)

if TYPE_CHECKING:
    from products.signals.backend.scout_harness.trial_result import TrialWorkflowStatus


@frozen
class TrialEvaluationInput:
    team_id: int
    evaluation_id: str


@frozen
class TrialEvaluationRunInput:
    team_id: int
    evaluation_id: str
    launch_id: str


@activity.defn
async def load_scout_trial_evaluation_activity(inputs: TrialEvaluationInput) -> list[str]:
    from products.signals.backend.scout_harness.trial_evaluation import (  # noqa: PLC0415 -- avoid loading the harness through the workflow registry
        read_trial_evaluation,
    )
    from products.signals.backend.scout_harness.trial_judge import (  # noqa: PLC0415 -- avoid loading judge dependencies through the workflow registry
        safe_judge_failure,
    )

    with private_capture_context():
        try:
            snapshot = await asyncio.to_thread(read_trial_evaluation, inputs.team_id, UUID(inputs.evaluation_id))
            if snapshot is None:
                raise ValueError("Missing evaluation")
            return [str(run.launch_id) for run in snapshot.runs]
        except Exception as error:
            raise ApplicationError(safe_judge_failure("snapshot_load", error)) from None


@activity.defn
async def poll_scout_trial_judge_activity(inputs: TrialEvaluationRunInput) -> bool:
    from products.signals.backend.scout_harness.trial_evaluation import (  # noqa: PLC0415 -- avoid loading the harness through the workflow registry
        run_evaluation_run,
    )
    from products.signals.backend.scout_harness.trial_judge import (  # noqa: PLC0415 -- avoid loading judge dependencies through the workflow registry
        safe_judge_failure,
    )
    from products.signals.backend.scout_harness.trial_launch import (  # noqa: PLC0415 -- keep trial dependencies off workflow imports
        ScoutTrialsDisabled,
    )

    with private_capture_context():
        try:
            async with Heartbeater():
                return await run_evaluation_run(inputs.team_id, UUID(inputs.evaluation_id), UUID(inputs.launch_id))
        except ScoutTrialsDisabled as error:
            raise ApplicationError(str(error), type="ScoutTrialsDisabled", non_retryable=True) from None
        except Exception as error:
            raise ApplicationError(safe_judge_failure("judge_activity", error)) from None


@activity.defn
async def judge_scout_trial_run_activity(inputs: TrialEvaluationRunInput) -> None:
    # Existing evaluation histories still schedule the long-lived activity during a rollout.
    while not await poll_scout_trial_judge_activity(inputs):
        await asyncio.sleep(10)


@activity.defn
async def finish_scout_trial_evaluation_activity(inputs: TrialEvaluationInput) -> None:
    from products.signals.backend.scout_harness.trial_evaluation import (  # noqa: PLC0415 -- avoid loading the harness through the workflow registry
        finish_trial_evaluation,
    )
    from products.signals.backend.scout_harness.trial_judge import (  # noqa: PLC0415 -- avoid loading judge dependencies through the workflow registry
        safe_judge_failure,
    )

    with private_capture_context():
        try:
            await database_sync_to_async(finish_trial_evaluation, thread_sensitive=False)(
                inputs.team_id, UUID(inputs.evaluation_id)
            )
        except Exception as error:
            raise ApplicationError(safe_judge_failure("report_save", error)) from None


@workflow.defn
class RunScoutTrialJudgeWorkflow:
    @workflow.run
    async def run(self, inputs: TrialEvaluationRunInput) -> None:
        deadline = workflow.now() + timedelta(minutes=TRIAL_JUDGE_TIMEOUT_MINUTES)
        while True:
            remaining = deadline - workflow.now()
            if remaining <= timedelta(0):
                raise ApplicationError("The judge status could not be collected before the evaluation deadline.")
            finished = await workflow.execute_activity(
                poll_scout_trial_judge_activity,
                inputs,
                start_to_close_timeout=min(timedelta(minutes=2), remaining),
                schedule_to_close_timeout=remaining,
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), maximum_interval=timedelta(seconds=30)),
            )
            if finished:
                return
            await workflow.sleep(timedelta(seconds=10))


def _trials_disabled(error: BaseException | None) -> bool:
    while isinstance(error, (ActivityError, ChildWorkflowError)):
        error = error.cause
    return isinstance(error, ApplicationError) and error.type == "ScoutTrialsDisabled"


@workflow.defn
class RunScoutTrialEvaluationWorkflow:
    @workflow.run
    async def run(self, inputs: TrialEvaluationInput) -> str:
        launch_ids = await workflow.execute_activity(
            load_scout_trial_evaluation_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            schedule_to_close_timeout=timedelta(minutes=3),
        )
        judge_timeout = timedelta(minutes=TRIAL_JUDGE_TIMEOUT_MINUTES)
        # Bound collectors; a timed-out collector can leave its Task running until its own deadline.
        semaphore = asyncio.Semaphore(TRIAL_JUDGE_CONCURRENCY)
        resumable_judges = workflow.patched("scout-trial-resumable-judges")

        async def score(launch_id: str) -> None:
            async with semaphore:
                run_input = TrialEvaluationRunInput(
                    team_id=inputs.team_id, evaluation_id=inputs.evaluation_id, launch_id=launch_id
                )
                if resumable_judges:
                    # Separate histories keep the largest supported trial below Temporal's event limit.
                    await workflow.execute_child_workflow(
                        RunScoutTrialJudgeWorkflow.run,
                        run_input,
                        id=f"{workflow.info().workflow_id}:judge:{launch_id}",
                        execution_timeout=judge_timeout,
                    )
                else:
                    # Preserve scheduled activity commands when replaying across a worker rollout.
                    await workflow.execute_activity(
                        judge_scout_trial_run_activity,
                        run_input,
                        start_to_close_timeout=judge_timeout,
                        heartbeat_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

        outcomes = await asyncio.gather(*(score(launch_id) for launch_id in launch_ids), return_exceptions=True)
        if any(_trials_disabled(outcome) for outcome in outcomes):
            raise ApplicationError("Scout trials are disabled. Resume when they are enabled again.", non_retryable=True)
        if resumable_judges and any(isinstance(outcome, BaseException) for outcome in outcomes):
            # Keep completed judgments, and let a retry reconnect to the remaining Tasks.
            raise ApplicationError("Some judge results could not be collected. Resume this evaluation to try again.")
        await workflow.execute_activity(
            finish_scout_trial_evaluation_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            schedule_to_close_timeout=timedelta(minutes=3),
        )
        return inputs.evaluation_id


def trial_evaluation_workflow_id(team_id: int, evaluation_id: UUID) -> str:
    return f"signals-scout-evaluation-{team_id}-{evaluation_id}"


@async_to_sync
async def start_trial_evaluation(team_id: int, evaluation_id: UUID) -> str:
    with private_capture_context():
        workflow_id = trial_evaluation_workflow_id(team_id, evaluation_id)
        client = await async_connect()
        try:
            await client.start_workflow(
                RunScoutTrialEvaluationWorkflow.run,
                TrialEvaluationInput(team_id=team_id, evaluation_id=str(evaluation_id)),
                id=workflow_id,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=timedelta(minutes=TRIAL_EVALUATION_TIMEOUT_MINUTES),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        except WorkflowAlreadyStartedError:
            pass
        return workflow_id


@async_to_sync
async def get_trial_evaluation_status(team_id: int, evaluation_id: UUID) -> TrialWorkflowStatus:
    from products.signals.backend.scout_harness.trial_result import (  # noqa: PLC0415 -- trial launch imports the Temporal registry through report tools
        TrialWorkflowStatus,
    )

    with private_capture_context():
        try:
            async with asyncio.timeout(5):
                client = await async_connect()
                handle = client.get_workflow_handle(trial_evaluation_workflow_id(team_id, evaluation_id))
                description = await handle.describe(rpc_timeout=timedelta(seconds=5))
                match description.status:
                    case WorkflowExecutionStatus.RUNNING | WorkflowExecutionStatus.CONTINUED_AS_NEW:
                        return TrialWorkflowStatus(status="pending")
                    case WorkflowExecutionStatus.COMPLETED:
                        return TrialWorkflowStatus(status="completed")
                    case WorkflowExecutionStatus.CANCELED | WorkflowExecutionStatus.TERMINATED:
                        return TrialWorkflowStatus(status="failed", error="The evaluation was canceled.")
                    case WorkflowExecutionStatus.TIMED_OUT | WorkflowExecutionStatus.FAILED:
                        return TrialWorkflowStatus(
                            status="failed",
                            error="The evaluation failed. Retry the same evaluation ID to resume saved work.",
                        )
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return TrialWorkflowStatus(
                    status="not_started", error="The evaluation has not started. Retry with the same ID."
                )
        except (TimeoutError, RuntimeError):
            pass
        return TrialWorkflowStatus(status="unknown", error="The evaluation status is unavailable. Try again.")
