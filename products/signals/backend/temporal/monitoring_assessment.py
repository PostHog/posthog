from datetime import timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect


@frozen
class MonitoringAssessmentInput:
    team_id: int
    report_id: str
    attempt_id: str
    execution: int = 0


@activity.defn
async def poll_monitoring_assessment_activity(
    inputs: MonitoringAssessmentInput,
) -> Literal["pending", "done", "errored"]:
    from products.signals.backend.report_monitoring_assessment import (  # noqa: PLC0415 -- keep agent dependencies off workflow imports
        poll_monitoring_assessment,
    )

    return await database_sync_to_async(poll_monitoring_assessment)(
        team_id=inputs.team_id,
        report_id=UUID(inputs.report_id),
        attempt_id=UUID(inputs.attempt_id),
        execution=inputs.execution,
    )


@activity.defn
async def exhaust_monitoring_assessment_activity(inputs: MonitoringAssessmentInput) -> bool:
    from products.signals.backend.report_monitoring_assessment import (  # noqa: PLC0415 -- keep agent dependencies off workflow imports
        finish_monitoring_assessment,
    )

    return await database_sync_to_async(finish_monitoring_assessment)(
        team_id=inputs.team_id, report_id=UUID(inputs.report_id), attempt_id=UUID(inputs.attempt_id)
    )


@workflow.defn
class MonitoringAssessmentWorkflow:
    @workflow.run
    async def run(self, inputs: MonitoringAssessmentInput) -> None:
        for execution in range(inputs.execution, 3):
            current = MonitoringAssessmentInput(
                team_id=inputs.team_id, report_id=inputs.report_id, attempt_id=inputs.attempt_id, execution=execution
            )
            while True:
                try:
                    result = await workflow.execute_activity(
                        poll_monitoring_assessment_activity,
                        current,
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except ActivityError:
                    # Do not launch another judgment when an interrupted collector may have a live task.
                    await self._exhaust(inputs)
                    return
                if result == "done":
                    return
                if result == "errored":
                    break
                await workflow.sleep(timedelta(seconds=30))
                if workflow.info().is_continue_as_new_suggested():
                    workflow.continue_as_new(current)
        await self._exhaust(inputs)

    async def _exhaust(self, inputs: MonitoringAssessmentInput) -> None:
        inputs = MonitoringAssessmentInput(
            team_id=inputs.team_id, report_id=inputs.report_id, attempt_id=inputs.attempt_id, execution=3
        )
        while not await workflow.execute_activity(
            exhaust_monitoring_assessment_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=2),
        ):
            await workflow.sleep(timedelta(seconds=30))
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(inputs)


async def start_monitoring_assessment(team_id: int, report_id: str, attempt_id: str) -> None:
    client = await async_connect()
    try:
        await client.start_workflow(
            MonitoringAssessmentWorkflow.run,
            MonitoringAssessmentInput(team_id=team_id, report_id=report_id, attempt_id=attempt_id),
            id=f"signals-monitoring-assessment-{team_id}-{attempt_id}",
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except WorkflowAlreadyStartedError:
        pass
