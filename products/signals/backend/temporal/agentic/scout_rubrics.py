from __future__ import annotations

from datetime import timedelta

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.scout_harness.rubrics import fail_generation


@frozen
class ScoutRubricGenerationInput:
    team_id: int
    config_id: str
    generation_id: str
    user_id: int


@activity.defn
@close_db_connections
async def generate_scout_rubrics_activity(input: ScoutRubricGenerationInput) -> None:
    from products.signals.backend.scout_harness.rubrics_runner import (  # noqa: PLC0415 - avoids the Temporal runner import cycle
        run_rubric_generation,
    )

    async with Heartbeater():
        await run_rubric_generation(input.team_id, input.config_id, input.generation_id, input.user_id)


@activity.defn
@close_db_connections
async def fail_scout_rubrics_activity(input: ScoutRubricGenerationInput) -> None:
    await database_sync_to_async(fail_generation, thread_sensitive=True)(
        input.team_id, input.config_id, input.generation_id, "Generation timed out or could not start. Try again."
    )


@workflow.defn(name="generate-scout-rubrics")
class GenerateScoutRubricsWorkflow:
    @workflow.run
    async def run(self, input: ScoutRubricGenerationInput) -> None:
        try:
            await workflow.execute_activity(
                generate_scout_rubrics_activity,
                input,
                start_to_close_timeout=timedelta(minutes=20),
                schedule_to_close_timeout=timedelta(minutes=25),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception:
            await workflow.execute_activity(
                fail_scout_rubrics_activity,
                input,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )


@async_to_sync
async def start_scout_rubric_generation(
    client: Client, *, team_id: int, config_id: str, generation_id: str, user_id: int
) -> None:
    await client.start_workflow(
        GenerateScoutRubricsWorkflow.run,
        ScoutRubricGenerationInput(team_id=team_id, config_id=config_id, generation_id=generation_id, user_id=user_id),
        id=f"scout-rubrics-{team_id}-{config_id}-{generation_id}",
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        execution_timeout=timedelta(minutes=27),
    )
