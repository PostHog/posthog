import asyncio
from datetime import timedelta

from django.conf import settings

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.monitor_pr import MonitorPRInput, fail_monitoring_research, monitor_pr_workflow_id


@activity.defn
async def research_monitored_pr_activity(inputs: MonitorPRInput) -> None:
    from products.signals.backend.monitor_pr_research import (
        research_pull_request,  # noqa: PLC0415 -- sandbox dependencies are activity-only
    )

    async with Heartbeater():
        await research_pull_request(inputs)


@activity.defn
async def fail_monitored_pr_activity(inputs: MonitorPRInput) -> None:
    await database_sync_to_async_pool(fail_monitoring_research)(inputs)


@workflow.defn
class MonitorPRWorkflow:
    @workflow.run
    async def run(self, inputs: MonitorPRInput) -> None:
        try:
            await workflow.execute_activity(
                research_monitored_pr_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=40),
                schedule_to_close_timeout=timedelta(minutes=50),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError:
            await workflow.execute_activity(
                fail_monitored_pr_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=1),
                schedule_to_close_timeout=timedelta(minutes=5),
            )
            raise


async def start_pr_monitoring(inputs: MonitorPRInput) -> None:
    async with asyncio.timeout(5):
        client = await async_connect()
        await client.start_workflow(
            MonitorPRWorkflow.run,
            inputs,
            id=monitor_pr_workflow_id(inputs.team_id, inputs.report_id, inputs.attempt_key),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=timedelta(minutes=60),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            rpc_timeout=timedelta(seconds=5),
        )
