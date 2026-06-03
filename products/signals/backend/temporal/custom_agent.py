from __future__ import annotations

import json
import uuid
import hashlib
import importlib
import dataclasses
from datetime import timedelta

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio import activity, workflow
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.custom_agent.base import AIDataProcessingNotApprovedError, CustomSignalAgent
from products.signals.backend.custom_agent.loader import import_agent_class, validate_agent_class_identity
from products.signals.backend.custom_agent.schemas import (
    AgentScheduleSpec,
    CustomAgentRunHandle,
    CustomAgentWorkflowInput,
    CustomAgentWorkflowOutput,
    ScheduleAgentResult,
    validate_run_id,
    validated_identifier,
)

# Static run_id for schedule-launched runs. Per-tick workflow-id uniqueness comes from
# Temporal appending the scheduled time to the action workflow-id, so this stays constant.
_SCHEDULED_RUN_ID = "scheduled"

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


def _schedule_id_for(agent_class: type[CustomSignalAgent], team_id: int) -> str:
    """Stable per-(team, agent) schedule id. One schedule per agent per team."""
    product, type_ = validated_identifier(agent_class)
    return f"signals-custom-agent:{team_id}:{product}:{type_}"


async def _assert_ai_processing_approved(team: Team) -> None:
    """Refuse to launch custom agents for orgs that haven't approved AI data processing.

    Custom agents send team data through LLMs and sandboxes, so this mirrors the consent
    gate in `emit_signal` / `_validate_ai_feature_access`. `team.organization` may be a
    deferred FK access, hence the `database_sync_to_async`.
    """
    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        raise AIDataProcessingNotApprovedError(
            f"Organization {organization.id} has not approved AI data processing; "
            f"refusing to launch custom signal agent for team {int(team.id)}"
        )


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
    await _assert_ai_processing_approved(team)
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
        scheduled=False,
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


# ----------------------------------------------------------------------
# Temporal-schedule launchers (recurring custom-agent runs)
# ----------------------------------------------------------------------


def _calendar_spec(schedule: AgentScheduleSpec) -> ScheduleCalendarSpec:
    """Map an `AgentScheduleSpec` onto a Temporal `ScheduleCalendarSpec`.

    Each set field becomes a list of single-value `ScheduleRange`s; unset fields are
    left at Temporal's defaults (which match every value).
    """

    def ranges(name: str) -> list[ScheduleRange]:
        # end=start makes each a single-value range, matching the batch-export idiom.
        return [ScheduleRange(start=value, end=value) for value in schedule.values_for(name)]

    kwargs: dict[str, list[ScheduleRange]] = {}
    for name in ("minute", "hour", "day_of_month", "month", "day_of_week"):
        values = ranges(name)
        if values:
            kwargs[name] = values
    # Timezone lives on the enclosing ScheduleSpec, not on the calendar spec.
    return ScheduleCalendarSpec(**kwargs)


def _schedule_fingerprint(input_data: CustomAgentWorkflowInput, schedule: AgentScheduleSpec, paused: bool) -> str:
    """Deterministic hash of the desired schedule config, stored in `ScheduleState.note`.

    Idempotency compares this against the existing schedule's note, which sidesteps
    Temporal's normalization of calendar specs on the read path.
    """
    payload = {
        "input": dataclasses.asdict(input_data),
        "schedule": dataclasses.asdict(schedule),
        "paused": paused,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"custom-agent-schedule:{hashlib.sha256(serialized.encode()).hexdigest()}"


async def aschedule_agent(
    agent_class: type[CustomSignalAgent],
    team: Team,
    initial_prompt: str,
    schedule: AgentScheduleSpec,
    *,
    repository: str | None = None,
    model: str | None = None,
    paused: bool = False,
) -> ScheduleAgentResult:
    """Idempotently register a recurring Temporal schedule for a custom agent.

    Keyed by ``(team_id, product, type)`` so each agent has at most one schedule per
    team. Calling with identical arguments is a no-op (``ALREADY_PRESENT``); changing
    the ``schedule`` or any run argument updates the existing schedule (``UPDATED``).

    Each tick starts the shared ``signals-custom-agent`` workflow with
    ``scheduled=True``. Overlap policy is ``SKIP``: an in-flight run is left to finish
    and an overlapping tick is dropped. Raises
    :class:`AIDataProcessingNotApprovedError` when the org hasn't approved AI data
    processing.
    """
    product, type_ = validated_identifier(agent_class)
    team_id = int(team.id)
    await _assert_ai_processing_approved(team)

    schedule_id = _schedule_id_for(agent_class, team_id)
    input_data = CustomAgentWorkflowInput(
        team_id=team_id,
        agent_path=_agent_import_path(agent_class),
        product=product,
        type=type_,
        run_id=_SCHEDULED_RUN_ID,
        initial_prompt=initial_prompt,
        repository=repository,
        model=model,
        scheduled=True,
    )
    fingerprint = _schedule_fingerprint(input_data, schedule, paused)
    desired = Schedule(
        action=ScheduleActionStartWorkflow(
            "signals-custom-agent",
            input_data,
            id=schedule_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            execution_timeout=timedelta(minutes=90),
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(calendars=[_calendar_spec(schedule)], time_zone_name=schedule.timezone),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        state=ScheduleState(note=fingerprint, paused=paused),
    )

    client = await async_connect()
    handle = client.get_schedule_handle(schedule_id)
    try:
        description = await handle.describe()
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
        await a_create_schedule(client, schedule_id, desired)
        return ScheduleAgentResult.CREATED

    if description.schedule.state.note == fingerprint:
        return ScheduleAgentResult.ALREADY_PRESENT
    await a_update_schedule(client, schedule_id, desired)
    return ScheduleAgentResult.UPDATED


def schedule_agent(
    agent_class: type[CustomSignalAgent],
    team: Team,
    initial_prompt: str,
    schedule: AgentScheduleSpec,
    *,
    repository: str | None = None,
    model: str | None = None,
    paused: bool = False,
) -> ScheduleAgentResult:
    """Sync wrapper around :func:`aschedule_agent`."""
    return async_to_sync(aschedule_agent)(
        agent_class,
        team,
        initial_prompt,
        schedule,
        repository=repository,
        model=model,
        paused=paused,
    )


async def aunschedule_agent(agent_class: type[CustomSignalAgent], team: Team) -> bool:
    """Delete the recurring schedule for a custom agent. Returns whether one existed."""
    schedule_id = _schedule_id_for(agent_class, int(team.id))
    client = await async_connect()
    if not await a_schedule_exists(client, schedule_id):
        return False
    await a_delete_schedule(client, schedule_id)
    return True


def unschedule_agent(agent_class: type[CustomSignalAgent], team: Team) -> bool:
    """Sync wrapper around :func:`aunschedule_agent`."""
    return async_to_sync(aunschedule_agent)(agent_class, team)


@activity.defn
@scoped_temporal()
async def run_custom_signal_agent_activity(inputs: CustomAgentWorkflowInput) -> CustomAgentWorkflowOutput:
    log = logger.bind(
        team_id=inputs.team_id,
        product=inputs.product,
        type=inputs.type,
        run_id=inputs.run_id,
        agent_path=inputs.agent_path,
        scheduled=inputs.scheduled,
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
                scheduled=inputs.scheduled,
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
