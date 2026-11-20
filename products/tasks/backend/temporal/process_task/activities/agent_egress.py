from pathlib import Path
from typing import Literal
from uuid import UUID

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.services.agent_egress_lifecycle import AgentEgressLifecycle
from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeConfig


@frozen
class AgentEgressProbeInput:
    config_path: str
    team_id: int
    run_id: str
    sandbox_id: str | None = None


@frozen
class AgentEgressExecutionInput:
    probe: AgentEgressProbeInput
    execution_id: str
    provisioning_deadline: float | None = None


@frozen
class AgentEgressPrepared:
    sandbox_id: str
    duration_seconds: int


@frozen
class AgentEgressCleanupInput:
    execution: AgentEgressExecutionInput
    sandbox_id: str | None
    reason: Literal["completed", "cancelled", "failed"]


def lifecycle(input: AgentEgressExecutionInput, *, cleanup: bool = False) -> AgentEgressLifecycle:
    config = AgentEgressProbeConfig.load(Path(input.probe.config_path), cleanup=cleanup)
    if config.team_id != input.probe.team_id or config.run_id != UUID(input.probe.run_id):
        raise ValueError("The worker configuration belongs to another run")
    config = config.model_copy(update={"sandbox_id": input.probe.sandbox_id})
    return AgentEgressLifecycle(
        config,
        execution_id=UUID(input.execution_id),
        workflow_run_id=activity.info().workflow_run_id or "",
        provisioning_deadline=input.provisioning_deadline,
    )


@asyncify
def _prepare(input: AgentEgressExecutionInput) -> AgentEgressPrepared:
    session = lifecycle(input)
    return AgentEgressPrepared(sandbox_id=session.prepare(), duration_seconds=session.config.duration_seconds)


@activity.defn
async def prepare_agent_egress(input: AgentEgressExecutionInput) -> AgentEgressPrepared:
    async with Heartbeater(factor=5):
        return await _prepare(input)


@activity.defn
@asyncify
def renew_agent_egress(input: AgentEgressExecutionInput) -> None:
    lifecycle(input).renew()


@asyncify
def _probe(input: AgentEgressExecutionInput) -> dict[int, int]:
    return lifecycle(input).probe()


@activity.defn
async def probe_agent_egress(input: AgentEgressExecutionInput) -> dict[int, int]:
    async with Heartbeater(factor=5):
        return await _probe(input)


@activity.defn
@asyncify
def cleanup_agent_egress(input: AgentEgressCleanupInput) -> None:
    lifecycle(input.execution, cleanup=True).close(reason=input.reason, sandbox_id=input.sandbox_id)
