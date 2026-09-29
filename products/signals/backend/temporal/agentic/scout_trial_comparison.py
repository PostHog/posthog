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
class TrialComparisonInput:
    team_id: int
    comparison_id: str


@activity.defn
async def dispatch_scout_trial_comparison_activity(inputs: TrialComparisonInput) -> None:
    from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- keep the harness off the workflow registry import path
        dispatch_trial_comparison,
    )

    with private_capture_context():
        async with Heartbeater():
            try:
                await database_sync_to_async(dispatch_trial_comparison, thread_sensitive=False)(
                    inputs.team_id, UUID(inputs.comparison_id)
                )
            except Exception:
                raise ApplicationError("The comparison's scout runs could not be started.") from None


@activity.defn
async def prepare_scout_trial_comparison_evaluation_activity(inputs: TrialComparisonInput) -> bool:
    from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- keep the harness off the workflow registry import path
        prepare_comparison_evaluation,
    )

    with private_capture_context():
        async with Heartbeater():
            try:
                return await database_sync_to_async(prepare_comparison_evaluation, thread_sensitive=False)(
                    inputs.team_id, UUID(inputs.comparison_id)
                )
            except Exception:
                raise ApplicationError("The comparison's saved results could not be prepared for judging.") from None


@activity.defn
async def finish_scout_trial_comparison_activity(inputs: TrialComparisonInput) -> bool:
    from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- keep the harness off the workflow registry import path
        comparison_evaluation_finished,
    )

    with private_capture_context():
        try:
            return await database_sync_to_async(comparison_evaluation_finished, thread_sensitive=False)(
                inputs.team_id, UUID(inputs.comparison_id)
            )
        except Exception:
            raise ApplicationError("The comparison report is unavailable. Resume to recover saved work.") from None


@activity.defn
async def fail_scout_trial_comparison_activity(inputs: TrialComparisonInput) -> None:
    from products.signals.backend.scout_harness.trial_comparison import (  # noqa: PLC0415 -- keep the harness off the workflow registry import path
        save_comparison_progress,
    )
    from products.signals.backend.scout_harness.trial_comparison_types import (  # noqa: PLC0415 -- keep the harness off the workflow registry import path
        TrialComparisonProgress,
    )

    with private_capture_context():
        try:
            await asyncio.to_thread(
                save_comparison_progress,
                inputs.team_id,
                UUID(inputs.comparison_id),
                TrialComparisonProgress(
                    status="failed",
                    error="The comparison stopped. Scout runs may still finish. Resume to recover saved work.",
                ),
            )
        except Exception:
            raise ApplicationError("The comparison status could not be saved.") from None


@workflow.defn
class RunScoutTrialComparisonWorkflow:
    @workflow.run
    async def run(self, inputs: TrialComparisonInput) -> str:
        try:
            return await self._run(inputs)
        except (ActivityError, ApplicationError, asyncio.CancelledError):
            await asyncio.shield(
                workflow.execute_activity(
                    fail_scout_trial_comparison_activity,
                    inputs,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )
            raise

    async def _run(self, inputs: TrialComparisonInput) -> str:
        await workflow.execute_activity(
            dispatch_scout_trial_comparison_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=3),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        deadline = workflow.now() + timedelta(minutes=35)
        while not await workflow.execute_activity(
            prepare_scout_trial_comparison_evaluation_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=3),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        ):
            if workflow.now() >= deadline:
                raise ApplicationError("The scout runs did not finish in time. Resume to check their saved results.")
            await workflow.sleep(10)
        deadline = workflow.now() + timedelta(minutes=45)
        while not await workflow.execute_activity(
            finish_scout_trial_comparison_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        ):
            if workflow.now() >= deadline:
                raise ApplicationError("Judging did not finish in time. Resume to check its saved results.")
            await workflow.sleep(10)
        return inputs.comparison_id


def trial_comparison_workflow_id(team_id: int, comparison_id: UUID) -> str:
    return f"signals-scout-comparison-{team_id}-{comparison_id}"


@async_to_sync
async def start_trial_comparison(team_id: int, comparison_id: UUID) -> str:
    with private_capture_context():
        workflow_id = trial_comparison_workflow_id(team_id, comparison_id)
        client = await async_connect()
        try:
            await client.start_workflow(
                RunScoutTrialComparisonWorkflow.run,
                TrialComparisonInput(team_id=team_id, comparison_id=str(comparison_id)),
                id=workflow_id,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=timedelta(minutes=90),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        except WorkflowAlreadyStartedError:
            pass
        return workflow_id


@async_to_sync
async def get_trial_comparison_status(team_id: int, comparison_id: UUID) -> TrialWorkflowStatus:
    from products.signals.backend.scout_harness.trial_result import (  # noqa: PLC0415 -- avoid the workflow registry import cycle
        TrialWorkflowStatus,
    )

    with private_capture_context():
        try:
            async with asyncio.timeout(5):
                client = await async_connect()
                handle = client.get_workflow_handle(trial_comparison_workflow_id(team_id, comparison_id))
                description = await handle.describe(rpc_timeout=timedelta(seconds=5))
                match description.status:
                    case WorkflowExecutionStatus.RUNNING | WorkflowExecutionStatus.CONTINUED_AS_NEW:
                        return TrialWorkflowStatus(status="pending")
                    case WorkflowExecutionStatus.COMPLETED:
                        return TrialWorkflowStatus(status="completed")
                    case WorkflowExecutionStatus.CANCELED | WorkflowExecutionStatus.TERMINATED:
                        return TrialWorkflowStatus(status="failed", error="The comparison was stopped.")
                    case WorkflowExecutionStatus.TIMED_OUT | WorkflowExecutionStatus.FAILED:
                        return TrialWorkflowStatus(
                            status="failed",
                            error="The comparison stopped. Resume to recover saved work without repeating runs.",
                        )
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return TrialWorkflowStatus(status="not_started", error="The comparison is saved but has not started.")
        except (TimeoutError, RuntimeError):
            pass
        return TrialWorkflowStatus(
            status="unknown", error="The comparison status is unavailable. Refresh to try again."
        )
