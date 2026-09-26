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
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater

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

    with private_capture_context():
        try:
            snapshot = await asyncio.to_thread(read_trial_evaluation, inputs.team_id, UUID(inputs.evaluation_id))
            if snapshot is None:
                raise ValueError("Missing evaluation")
            return [str(run.launch_id) for run in snapshot.runs]
        except Exception:
            raise ApplicationError("The saved evaluation could not be loaded.", non_retryable=True) from None


@activity.defn
async def judge_scout_trial_run_activity(inputs: TrialEvaluationRunInput) -> None:
    from products.signals.backend.scout_harness.trial_evaluation import (  # noqa: PLC0415 -- avoid loading the harness through the workflow registry
        run_evaluation_run,
    )

    with private_capture_context():
        try:
            async with Heartbeater():
                await run_evaluation_run(inputs.team_id, UUID(inputs.evaluation_id), UUID(inputs.launch_id))
        except Exception:
            raise ApplicationError("The trial could not be scored.", non_retryable=True) from None


@activity.defn
async def finish_scout_trial_evaluation_activity(inputs: TrialEvaluationInput) -> None:
    from products.signals.backend.scout_harness.trial_evaluation import (  # noqa: PLC0415 -- avoid loading the harness through the workflow registry
        finish_trial_evaluation,
    )

    with private_capture_context():
        try:
            await database_sync_to_async(finish_trial_evaluation, thread_sensitive=False)(
                inputs.team_id, UUID(inputs.evaluation_id)
            )
        except Exception:
            raise ApplicationError("The evaluation report could not be saved.", non_retryable=True) from None


@workflow.defn
class RunScoutTrialEvaluationWorkflow:
    @workflow.run
    async def run(self, inputs: TrialEvaluationInput) -> str:
        launch_ids = await workflow.execute_activity(
            load_scout_trial_evaluation_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        semaphore = asyncio.Semaphore(3)

        async def score(launch_id: str) -> None:
            async with semaphore:
                try:
                    await workflow.execute_activity(
                        judge_scout_trial_run_activity,
                        TrialEvaluationRunInput(
                            team_id=inputs.team_id, evaluation_id=inputs.evaluation_id, launch_id=launch_id
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        heartbeat_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except ActivityError:
                    # Finalization records missing outcomes without buying another judge call.
                    pass

        await asyncio.gather(*(score(launch_id) for launch_id in launch_ids))
        await workflow.execute_activity(
            finish_scout_trial_evaluation_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
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
                execution_timeout=timedelta(minutes=40),
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
