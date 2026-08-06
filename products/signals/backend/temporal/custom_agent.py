from __future__ import annotations

import uuid
import importlib
from datetime import timedelta

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.custom_agent.base import AIDataProcessingNotApprovedError, CustomSignalAgent
from products.signals.backend.custom_agent.loader import import_agent_class, validate_agent_class_identity
from products.signals.backend.custom_agent.schemas import (
    CustomAgentRunHandle,
    CustomAgentWorkflowInput,
    CustomAgentWorkflowOutput,
    validate_run_id,
    validated_identifier,
)

logger = structlog.get_logger(__name__)


@workflow.defn(name="signals-custom-agent")
class CustomSignalAgentWorkflow:
    @workflow.run
    async def run(self, inputs: CustomAgentWorkflowInput) -> CustomAgentWorkflowOutput:
        return await workflow.execute_activity(
            run_custom_signal_agent_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=85),
            # Heartbeater() in the activity beats continuously while the agent thinks; a 2-min
            # heartbeat_timeout lets Temporal detect a dead/stuck worker within minutes instead
            # of waiting out the full 85-min start_to_close. With maximum_attempts=1 a missed
            # heartbeat fails the run (no duplicate sandbox tasks from a retry).
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


# ----------------------------------------------------------------------
# Public Temporal launchers (the "convenient pre-built utilities")
# ----------------------------------------------------------------------


def _workflow_id_for(agent_class: type[CustomSignalAgent], team_id: int, run_id: str) -> str:
    product, type_ = validated_identifier(agent_class)
    return f"signals-custom-agent:{team_id}:{product}:{type_}-{validate_run_id(run_id)}"


def _agent_import_path(agent_class: type[CustomSignalAgent]) -> str:
    module_name = agent_class.__module__
    class_name = agent_class.__qualname__
    if module_name == "__main__":
        raise RuntimeError("Custom signal agents must live in an importable module, not __main__")
    if "." in class_name:
        raise RuntimeError(
            f"Custom signal agent {module_name}.{class_name} is nested/local. Define it as a top-level class."
        )
    module = importlib.import_module(module_name)
    if getattr(module, class_name, None) is not agent_class:
        raise RuntimeError(f"Custom signal agent path {module_name}.{class_name} does not import this class")
    return f"{module_name}.{class_name}"


async def arun_agent(
    agent_class: type[CustomSignalAgent],
    team: Team,
    initial_prompt: str,
    *,
    repository: str | None = None,
    id: str | None = None,
    model: str | None = None,
) -> CustomAgentRunHandle:
    """Start the shared ``signals-custom-agent`` Temporal workflow for an agent class.

    Fire-and-forget: returns immediately with a :py:class:`CustomAgentRunHandle`
    carrying the workflow id, run id, and whether this call actually started a
    new workflow. Reusing the same ``id`` while a workflow is already running
    returns ``started=False`` instead of raising.

    Raises :py:class:`AIDataProcessingNotApprovedError` when the team's
    organization has not approved AI data processing.
    """
    product, type_ = validated_identifier(agent_class)
    run_id = validate_run_id(id) if id is not None else str(uuid.uuid4())
    team_id = int(team.id)
    # Mirrors the consent gate in `emit_signal` / `_validate_ai_feature_access`.
    # Custom agents send team data through LLMs and sandboxes, so refuse to launch
    # without org-level consent. `team.organization` may be a deferred FK access.
    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        raise AIDataProcessingNotApprovedError(
            f"Organization {organization.id} has not approved AI data processing; "
            f"refusing to launch custom signal agent for team {team_id}"
        )
    workflow_id = _workflow_id_for(agent_class, team_id, run_id)
    input_data = CustomAgentWorkflowInput(
        team_id=team_id,
        agent_path=_agent_import_path(agent_class),
        product=product,
        type=type_,
        run_id=run_id,
        initial_prompt=initial_prompt,
        repository=repository,
        model=model,
    )

    client = await async_connect()
    try:
        await client.start_workflow(
            "signals-custom-agent",
            input_data,
            id=workflow_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=timedelta(minutes=90),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        started = True
    except WorkflowAlreadyStartedError:
        started = False

    return CustomAgentRunHandle(workflow_id=workflow_id, run_id=run_id, started=started)


def run_agent(
    agent_class: type[CustomSignalAgent],
    team: Team,
    initial_prompt: str,
    *,
    repository: str | None = None,
    id: str | None = None,
    model: str | None = None,
) -> CustomAgentRunHandle:
    """Sync wrapper around :func:`arun_agent`. Returns immediately."""
    return async_to_sync(arun_agent)(
        agent_class,
        team,
        initial_prompt,
        repository=repository,
        id=id,
        model=model,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def run_custom_signal_agent_activity(inputs: CustomAgentWorkflowInput) -> CustomAgentWorkflowOutput:
    log = logger.bind(
        team_id=inputs.team_id,
        product=inputs.product,
        type=inputs.type,
        run_id=inputs.run_id,
        agent_path=inputs.agent_path,
    )
    try:
        async with Heartbeater():
            agent_class = import_agent_class(inputs.agent_path)
            validate_agent_class_identity(agent_class, inputs.product, inputs.type)
            team = await Team.objects.select_related("organization").aget(pk=inputs.team_id)
            agent = agent_class(
                team=team,
                initial_prompt=inputs.initial_prompt,
                repository=inputs.repository,
                model=inputs.model,
            )
            persisted_reports = await agent.start()
            report_ids = [r.report_id for r in persisted_reports]
            task_id = persisted_reports[0].task_id if persisted_reports else None
            log.info(
                "custom signal agent completed",
                report_ids=report_ids,
                report_count=len(report_ids),
                repository=agent.repository,
                task_id=task_id,
            )
            return CustomAgentWorkflowOutput(
                report_ids=report_ids,
                repository=agent.repository,
                task_id=task_id,
            )
    except Exception as exc:
        log.exception("custom signal agent failed", error=str(exc))
        raise
