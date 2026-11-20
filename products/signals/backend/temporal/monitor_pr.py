import asyncio
from datetime import timedelta

from django.conf import settings

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.monitor_pr import MonitorPRInput, fail_monitoring_research, refresh_monitored_pr


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


@activity.defn
async def refresh_monitored_pr_activity(inputs: MonitorPRInput) -> bool:
    return await database_sync_to_async_pool(refresh_monitored_pr)(inputs)


@workflow.defn
class MonitorPRWorkflow:
    @workflow.run
    async def run(self, inputs: MonitorPRInput) -> None:
        try:
            await workflow.execute_activity(
                research_monitored_pr_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=40),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError:
            await workflow.execute_activity(
                fail_monitored_pr_activity, inputs, start_to_close_timeout=timedelta(minutes=1)
            )
            raise
        while await workflow.execute_activity(
            refresh_monitored_pr_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(initial_interval=timedelta(minutes=1), maximum_interval=timedelta(minutes=30)),
        ):
            await workflow.sleep(timedelta(minutes=30))
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(inputs)


async def start_pr_monitoring(inputs: MonitorPRInput) -> None:
    async with asyncio.timeout(5):
        client = await async_connect()
        try:
            await client.start_workflow(
                MonitorPRWorkflow.run,
                inputs,
                id=f"signals-monitor-pr-{inputs.team_id}-{inputs.report_id}",
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                rpc_timeout=timedelta(seconds=5),
            )
        except WorkflowAlreadyStartedError:
            pass
