from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.conf import settings

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.report_canvas import (
    ReportCanvasGeneration,
    ensure_and_start_report_canvas_generation,
    fail_report_canvas_generation,
    finalize_report_canvas_generation,
    report_canvases_enabled,
)


@dataclass(frozen=True, kw_only=True)
class ReportCanvasWorkflowInput:
    team_id: int
    report_id: str
    notify_reviewers: bool = True


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def report_canvases_enabled_activity(team_id: int) -> bool:
    try:
        team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=team_id)
    except Team.DoesNotExist:
        return False
    return await database_sync_to_async(report_canvases_enabled, thread_sensitive=False)(team)


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def start_report_canvas_generation_activity(
    input: ReportCanvasWorkflowInput,
) -> ReportCanvasGeneration | None:
    return await database_sync_to_async(ensure_and_start_report_canvas_generation, thread_sensitive=False)(
        team_id=input.team_id,
        report_id=input.report_id,
    )


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def poll_report_canvas_generation_activity(
    input: ReportCanvasWorkflowInput, generation: ReportCanvasGeneration
) -> bool | None:
    return await database_sync_to_async(finalize_report_canvas_generation, thread_sensitive=False)(
        team_id=input.team_id,
        report_id=input.report_id,
        generation=generation,
        notify_reviewers=input.notify_reviewers,
    )


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def fail_report_canvas_generation_activity(input: ReportCanvasWorkflowInput, generation_task_id: UUID) -> None:
    await database_sync_to_async(fail_report_canvas_generation, thread_sensitive=False)(
        team_id=input.team_id,
        report_id=input.report_id,
        generation_task_id=generation_task_id,
    )


@temporalio.workflow.defn(name="signal-report-canvas")
class SignalReportCanvasWorkflow:
    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signals-report-canvas:{team_id}:{report_id}"

    @temporalio.workflow.run
    async def run(self, input: ReportCanvasWorkflowInput) -> bool | None:
        for _ in range(3):
            generation = await workflow.execute_activity(
                start_report_canvas_generation_activity,
                input,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if generation is None:
                return None
            if generation.skipped:
                return True
            for _ in range(480):
                result = await workflow.execute_activity(
                    poll_report_canvas_generation_activity,
                    args=[input, generation],
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if result is not None:
                    if not result:
                        return False
                    break
                await workflow.sleep(timedelta(seconds=30))
            else:
                if generation.generation_task_id is not None:
                    await workflow.execute_activity(
                        fail_report_canvas_generation_activity,
                        args=[input, generation.generation_task_id],
                        start_to_close_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                return False
        return True


async def start_report_canvas_workflow(*, team_id: int, report_id: str, notify_reviewers: bool = True) -> bool:
    client = await async_connect()
    try:
        await client.start_workflow(
            SignalReportCanvasWorkflow.run,
            ReportCanvasWorkflowInput(
                team_id=team_id,
                report_id=report_id,
                notify_reviewers=notify_reviewers,
            ),
            id=SignalReportCanvasWorkflow.workflow_id_for(team_id, report_id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=timedelta(hours=5),
        )
        return True
    except WorkflowAlreadyStartedError:
        return False
