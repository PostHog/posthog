from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.services.agent_egress import AGENT_EGRESS_LEASE_DURATION
from products.tasks.backend.logic.services.agent_egress_enrollment import AgentEgressRunConfig
from products.tasks.backend.logic.services.agent_egress_lifecycle import (
    AgentEgressLifecycle,
    AgentEgressOwnershipConflict,
    AgentEgressRunEnded,
)
from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeConfig


@frozen
class AgentEgressProbeInput:
    config_path: str
    team_id: int
    run_id: str
    sandbox_id: str | None = None
    enrollment: bool = False
    sandbox_expires_at: float | None = None


@frozen
class AgentEgressExecutionInput:
    probe: AgentEgressProbeInput
    execution_id: str
    provisioning_deadline: float | None = None


@frozen
class AgentEgressPrepared:
    sandbox_id: str
    duration_seconds: int
    enrollment_expires_at: float | None = None


@frozen
class AgentEgressCleanupInput:
    execution: AgentEgressExecutionInput
    sandbox_id: str | None
    reason: Literal["completed", "cancelled", "failed"]


@contextmanager
def lifecycle(input: AgentEgressExecutionInput, *, cleanup: bool = False) -> Iterator[AgentEgressLifecycle]:
    if input.probe.enrollment:
        if input.probe.sandbox_id is None:
            raise ValueError("Agent egress enrollment requires a provisioned sandbox")
        config: AgentEgressProbeConfig = AgentEgressRunConfig.for_run(
            team_id=input.probe.team_id, run_id=UUID(input.probe.run_id), sandbox_id=input.probe.sandbox_id
        )
    else:
        config = AgentEgressProbeConfig.load(Path(input.probe.config_path), cleanup=cleanup)
    if config.team_id != input.probe.team_id or config.run_id != UUID(input.probe.run_id):
        raise ValueError("The worker configuration belongs to another run")
    config = config.model_copy(update={"sandbox_id": input.probe.sandbox_id})
    session = AgentEgressLifecycle(
        config,
        execution_id=UUID(input.execution_id),
        workflow_run_id=activity.info().workflow_run_id or "",
        provisioning_deadline=input.provisioning_deadline,
        sandbox_expires_at=input.probe.sandbox_expires_at,
    )
    try:
        yield session
    except AgentEgressRunEnded as error:
        raise ApplicationError(str(error), error.status, type="AgentEgressRunEnded", non_retryable=True) from error
    except AgentEgressOwnershipConflict as error:
        raise ApplicationError(
            str(error), type="AgentEgressOwnershipConflict", next_retry_delay=AGENT_EGRESS_LEASE_DURATION
        ) from error


@asyncify
def _prepare(input: AgentEgressExecutionInput) -> AgentEgressPrepared:
    with lifecycle(input) as session:
        sandbox_id = session.prepare()
        return AgentEgressPrepared(
            sandbox_id=sandbox_id,
            duration_seconds=session.config.duration_seconds,
            enrollment_expires_at=session.enrollment_expires_at,
        )


@activity.defn
async def prepare_agent_egress(input: AgentEgressExecutionInput) -> AgentEgressPrepared:
    async with Heartbeater(factor=5):
        return await _prepare(input)


@activity.defn
@asyncify
def renew_agent_egress(input: AgentEgressExecutionInput) -> None:
    with lifecycle(input) as session:
        session.renew()


@asyncify
def _probe(input: AgentEgressExecutionInput) -> dict[int, int]:
    with lifecycle(input) as session:
        return session.probe()


@activity.defn
async def probe_agent_egress(input: AgentEgressExecutionInput) -> dict[int, int]:
    async with Heartbeater(factor=5):
        return await _probe(input)


@activity.defn
@asyncify
def cleanup_agent_egress(input: AgentEgressCleanupInput) -> None:
    execution = input.execution
    AgentEgressLifecycle.close_execution(
        team_id=execution.probe.team_id,
        run_id=UUID(execution.probe.run_id),
        execution_id=UUID(execution.execution_id),
        workflow_run_id=activity.info().workflow_run_id or "",
        provisioning_deadline=execution.provisioning_deadline,
        sandbox_id=execution.probe.sandbox_id or input.sandbox_id,
        owns_sandbox=execution.probe.sandbox_id is None,
        reason=input.reason,
    )
