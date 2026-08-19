from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.agent_runtime import STEP_FEATURE_DISCOVERY, resolve_agent_runtime
from products.signals.backend.features.discovery import persist_discovered_features, run_multi_turn_feature_discovery
from products.signals.backend.features.types import FeatureDiscoveryWorkflowInput
from products.signals.backend.models import FeatureDiscoveryRun
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPORT_RESEARCH_ENV_NAME,
    get_or_create_signals_sandbox_env,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)


@frozen
class FeatureDiscoveryFailedInput:
    run_id: str
    team_id: int
    error: str


def _get_discovery_run(team_id: int, run_id: str) -> FeatureDiscoveryRun:
    return FeatureDiscoveryRun.objects.for_team(team_id).get(id=run_id)


def _mark_discovery_running(team_id: int, run_id: str) -> None:
    FeatureDiscoveryRun.objects.for_team(team_id).filter(id=run_id).update(
        status=FeatureDiscoveryRun.Status.RUNNING,
        error="",
        updated_at=timezone.now(),
    )


def _link_discovery_task_sync(team_id: int, run_id: str, task_id: str) -> None:
    FeatureDiscoveryRun.objects.for_team(team_id).filter(id=run_id).update(
        task_id=task_id,
        status=FeatureDiscoveryRun.Status.RUNNING,
        error="",
        updated_at=timezone.now(),
    )


def _mark_discovery_failed(team_id: int, run_id: str) -> None:
    (
        FeatureDiscoveryRun.objects.for_team(team_id)
        .filter(id=run_id)
        .exclude(status=FeatureDiscoveryRun.Status.COMPLETED)
        .update(
            status=FeatureDiscoveryRun.Status.FAILED,
            error="Feature discovery failed. Check the repository connection and try again.",
            updated_at=timezone.now(),
        )
    )


@temporalio.workflow.defn(name="feature-discovery")
class FeatureDiscoveryWorkflow:
    @staticmethod
    def workflow_id_for(team_id: int, run_id: str) -> str:
        return f"signals-feature-discovery:{team_id}:{run_id}"

    @temporalio.workflow.run
    async def run(self, input: FeatureDiscoveryWorkflowInput) -> int:
        try:
            return await temporalio.workflow.execute_activity(
                run_feature_discovery_activity,
                input,
                start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as error:
            await temporalio.workflow.execute_activity(
                mark_feature_discovery_failed_activity,
                FeatureDiscoveryFailedInput(
                    run_id=input.run_id,
                    team_id=input.team_id,
                    error=str(error)[:8000],
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


async def _link_discovery_task(input: FeatureDiscoveryWorkflowInput, task_run: TaskRun) -> None:
    await database_sync_to_async(_link_discovery_task_sync, thread_sensitive=False)(
        input.team_id,
        input.run_id,
        str(task_run.task_id),
    )


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def run_feature_discovery_activity(input: FeatureDiscoveryWorkflowInput) -> int:
    run = await database_sync_to_async(_get_discovery_run, thread_sensitive=False)(input.team_id, input.run_id)
    if run.status == FeatureDiscoveryRun.Status.COMPLETED:
        return run.discovered_count

    await database_sync_to_async(_mark_discovery_running, thread_sensitive=False)(input.team_id, input.run_id)
    try:
        async with Heartbeater():
            sandbox_env_id = await database_sync_to_async(
                get_or_create_signals_sandbox_env,
                thread_sensitive=False,
            )(
                input.team_id,
                SIGNALS_REPORT_RESEARCH_ENV_NAME,
                tasks_facade.SandboxNetworkAccessLevel.TRUSTED,
            )
            agent_runtime = await database_sync_to_async(resolve_agent_runtime, thread_sensitive=False)(
                input.team_id,
                STEP_FEATURE_DISCOVERY,
            )
            context = CustomPromptSandboxContext(
                team_id=input.team_id,
                user_id=input.user_id,
                repository=input.repository,
                sandbox_environment_id=sandbox_env_id,
                posthog_mcp_scopes="read_only",
                model=agent_runtime.model,
                runtime_adapter=agent_runtime.runtime_adapter,
                reasoning_effort=agent_runtime.reasoning_effort,
            )
            result = await run_multi_turn_feature_discovery(
                repository=input.repository,
                focus=input.focus,
                context=context,
                on_task_run_created=lambda task_run: _link_discovery_task(input, task_run),
            )
            discovered_count = await database_sync_to_async(persist_discovered_features, thread_sensitive=True)(
                run_id=input.run_id,
                team_id=input.team_id,
                result=result,
            )
        logger.info(
            "feature discovery completed",
            run_id=input.run_id,
            team_id=input.team_id,
            repository=input.repository,
            discovered_count=discovered_count,
        )
        return discovered_count
    except Exception as error:
        logger.exception(
            "feature discovery activity failed",
            run_id=input.run_id,
            team_id=input.team_id,
            repository=input.repository,
            error=str(error),
        )
        raise


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def mark_feature_discovery_failed_activity(input: FeatureDiscoveryFailedInput) -> None:
    logger.error(
        "feature discovery workflow failed",
        run_id=input.run_id,
        team_id=input.team_id,
        error=input.error,
    )
    await database_sync_to_async(_mark_discovery_failed, thread_sensitive=False)(input.team_id, input.run_id)
