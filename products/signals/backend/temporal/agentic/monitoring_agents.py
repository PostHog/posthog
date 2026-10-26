from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.report_monitoring_results import InvalidMonitoringResult
from products.signals.backend.scout_harness.limits import DEFAULT_MAX_RUNTIME_S, WORKFLOW_HARD_CEILING_S


@frozen
class MonitoringAgentInput:
    team_id: int
    evaluation_id: str


@activity.defn
@scoped_temporal()
@close_db_connections
async def run_monitoring_agent_activity(input: MonitoringAgentInput) -> None:
    from products.signals.backend.report_check_agent_runner import (
        run_monitoring_agent,  # noqa: PLC0415 - keeps the heavy sandbox runner off worker registration imports
    )

    async with Heartbeater():
        await run_monitoring_agent(team_id=input.team_id, evaluation_id=UUID(input.evaluation_id))


@activity.defn
@scoped_temporal()
@close_db_connections
async def finish_monitoring_agent_activity(input: MonitoringAgentInput) -> None:
    from products.signals.backend.report_check_final_agents import (
        fail_agent_evaluation,  # noqa: PLC0415 - keeps result recovery lazy
    )

    try:
        await database_sync_to_async(fail_agent_evaluation, thread_sensitive=False)(
            team_id=input.team_id, evaluation_id=UUID(input.evaluation_id)
        )
    except InvalidMonitoringResult:
        return


@workflow.defn
class MonitoringAgentWorkflow:
    @workflow.run
    async def run(self, input: MonitoringAgentInput) -> None:
        try:
            await workflow.execute_activity(
                run_monitoring_agent_activity,
                input,
                start_to_close_timeout=timedelta(seconds=WORKFLOW_HARD_CEILING_S),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        finally:
            await workflow.execute_activity(
                finish_monitoring_agent_activity,
                input,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )


@async_to_sync
async def start_monitoring_agent(client: Client, *, team_id: int, evaluation_id: str) -> None:
    await client.start_workflow(
        MonitoringAgentWorkflow.run,
        MonitoringAgentInput(team_id=team_id, evaluation_id=evaluation_id),
        id=f"monitoring-agent-{team_id}-{evaluation_id}",
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        execution_timeout=timedelta(seconds=WORKFLOW_HARD_CEILING_S + DEFAULT_MAX_RUNTIME_S),
    )
