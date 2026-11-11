"""Workflow for one pass of an agent over an entity that another product asked Self-driving to look at.

The workflow carries only the id of its `SignalAgentRun` row. Each activity loads what it needs by
that id, so the entity's content never travels through Temporal.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from django.conf import settings
from django.db import transaction

import structlog
import temporalio
from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError, WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.agent_run_passes import (
    REASON_AGENT_RUN_FAILED,
    REASON_ENTITY_GONE,
    REASON_INPUT_TOO_LARGE,
    REASON_RUN_IN_FLIGHT,
    REASON_UNSAFE_CONTENT,
    PassOutcome,
    agent_scout_for,
    begin_pass,
    build_run_note,
    complete_pass,
    ensure_agent_scout_config,
    entity_key,
    entity_of,
    pass_outcome,
    safety_chunks,
)
from products.signals.backend.agent_run_requests import dispatch_agent_run
from products.signals.backend.agent_run_types import AgentEntityContent, AgentRunOutcome
from products.signals.backend.facade.agent_sources import deliver_agent_run_result, load_agent_entity
from products.signals.backend.models import SignalAgentRun
from products.signals.backend.scout_harness.limits import TRIGGERED_BY_AGENT_RUN, WORKFLOW_HARD_CEILING_S
from products.signals.backend.scout_harness.run_gates import check_run_in_flight
from products.signals.backend.temporal.agentic.scout_scheduler import (
    RunSignalsScoutInput,
    RunSignalsScoutWorkflow,
    agent_run_scout_workflow_id,
)
from products.signals.backend.temporal.safety_filter import safety_filter

logger = structlog.get_logger(__name__)


@frozen
class AgentRunWorkflowInput:
    run_id: str


@frozen
class PrepareAgentRunOutput:
    """Whether the agent can start, with what the scout run needs, or how the pass ended without one.

    `proceed=False` with no outcome means that the pass is settled already or its row is gone, so
    nothing is left to finish.
    """

    proceed: bool
    team_id: int = 0
    skill_name: str = ""
    run_note: str = ""
    scout_workflow_id: str = ""
    outcome: str | None = None
    reason_code: str | None = None


@frozen
class FinishAgentRunInput:
    """What the agent's scout run reported, or the outcome of a pass that ended before the agent ran."""

    run_id: str
    scout_run_id: str | None = None
    scout_status: str | None = None
    scout_skip_reason: str | None = None
    outcome: str | None = None
    reason_code: str | None = None


def _ended(outcome: AgentRunOutcome, reason_code: str) -> PrepareAgentRunOutput:
    return PrepareAgentRunOutput(proceed=False, outcome=outcome.value, reason_code=reason_code)


@frozen
class _LoadedPass:
    run: SignalAgentRun
    team: Team
    content: AgentEntityContent


def _load_pass(run_id: str) -> _LoadedPass | PrepareAgentRunOutput:
    # The row stays locked while the entity loads. A request that arrives now then sees either no
    # hash, and this pass reads the entity after it, or the hash of what this pass read.
    with transaction.atomic():
        run = SignalAgentRun.all_teams.select_for_update().filter(id=run_id).first()
        if run is None or run.status not in SignalAgentRun.ACTIVE_STATUSES:
            return PrepareAgentRunOutput(proceed=False)
        team = Team.objects.select_related("organization").get(id=run.team_id)
        content = load_agent_entity(team_id=team.id, agent=run.agent, entity=entity_of(run))
        if content is None:
            return _ended(AgentRunOutcome.FAILED, REASON_ENTITY_GONE)
        run.content_hash = content.content_hash
        run.save(update_fields=["content_hash", "updated_at"])
    return _LoadedPass(run=run, team=team, content=content)


def _start_pass(loaded: _LoadedPass) -> PrepareAgentRunOutput:
    run, team = loaded.run, loaded.team
    entity = entity_of(run)
    scout = agent_scout_for(run.agent, entity)
    if scout is None:
        return _ended(AgentRunOutcome.FAILED, REASON_AGENT_RUN_FAILED)
    key = entity_key(entity)
    # A scout run of an earlier pass can outlive its workflow. The runner would refuse to start a
    # second run for the entity, so the pass ends here and spends nothing.
    if check_run_in_flight(team.id, scout.skill_name, agent_run_entity=key) is not None:
        return _ended(AgentRunOutcome.FAILED, REASON_RUN_IN_FLIGHT)
    ensure_agent_scout_config(team, scout, entity)
    if not begin_pass(run_id=str(run.id)):
        return PrepareAgentRunOutput(proceed=False)
    return PrepareAgentRunOutput(
        proceed=True,
        team_id=team.id,
        skill_name=scout.skill_name,
        run_note=build_run_note(run=run, url=loaded.content.url),
        scout_workflow_id=agent_run_scout_workflow_id(team.id, scout.skill_name, key),
    )


@temporalio.activity.defn
@close_db_connections
async def prepare_agent_run_activity(input: AgentRunWorkflowInput) -> PrepareAgentRunOutput:
    """Load the entity, screen all of its text, and mark the pass as running.

    The screen fails closed: an error from the safety model fails the activity, and a pass whose
    text was not screened never starts an agent.
    """
    loaded = await database_sync_to_async(_load_pass, thread_sensitive=False)(input.run_id)
    if isinstance(loaded, PrepareAgentRunOutput):
        return loaded
    run = loaded.run
    chunks = safety_chunks(f"{loaded.content.title}\n\n{loaded.content.text}")
    if chunks is None:
        return _ended(AgentRunOutcome.BLOCKED, REASON_INPUT_TOO_LARGE)
    async with Heartbeater():
        for chunk in chunks:
            verdict = await safety_filter(run.team_id, chunk, run.source_product, run.source_type, run.source_id)
            if not verdict.safe:
                logger.info(
                    "signals_agent_run_blocked",
                    run_id=input.run_id,
                    team_id=run.team_id,
                    threat_type=verdict.threat_type,
                )
                return _ended(AgentRunOutcome.BLOCKED, REASON_UNSAFE_CONTENT)
    return await database_sync_to_async(_start_pass, thread_sensitive=False)(loaded)


@temporalio.activity.defn
@close_db_connections
def finish_agent_run_activity(input: FinishAgentRunInput) -> None:
    """Settle the pass, start the pass a waiting request asked for, and tell the owning product.

    Safe to retry: a settled pass returns its stored result, the next pass's workflow id is
    derived from its row, and the product's handler dedupes on the run id.
    """
    run = SignalAgentRun.all_teams.filter(id=input.run_id).first()
    if run is None:
        return
    # The owning product can delete the entity during the pass. Nothing derived from it is kept then.
    entity_exists = load_agent_entity(team_id=run.team_id, agent=run.agent, entity=entity_of(run)) is not None
    outcome = pass_outcome(
        ended_early=(
            PassOutcome(outcome=AgentRunOutcome(input.outcome), reason_code=input.reason_code)
            if input.outcome
            else None
        ),
        scout_status=input.scout_status,
        scout_skip_reason=input.scout_skip_reason,
        output=run.output,
    )
    if not entity_exists:
        outcome = PassOutcome(outcome=AgentRunOutcome.FAILED, reason_code=REASON_ENTITY_GONE)
    completed = complete_pass(
        run_id=input.run_id, outcome=outcome, scout_run_id=input.scout_run_id, keep_output=entity_exists
    )
    if completed is None:
        return
    # The next pass is dispatched first, so a handler that keeps failing cannot hold it back.
    if completed.next_run_id is not None:
        dispatch_agent_run(completed.next_run_id)
    if entity_exists:
        deliver_agent_run_result(completed.result)


@temporalio.workflow.defn(name="signals-agent-run")
class SignalsAgentRunWorkflow:
    """Drives one pass: prepare, run the agent as a scout run, finish.

    Every path that started a pass reaches the finish activity, so each accepted request gets
    exactly one result, also when the agent's run times out or its worker dies.
    """

    @temporalio.workflow.run
    async def run(self, input: AgentRunWorkflowInput) -> None:
        finish = FinishAgentRunInput(
            run_id=input.run_id, outcome=AgentRunOutcome.FAILED.value, reason_code=REASON_AGENT_RUN_FAILED
        )
        try:
            prepared = await temporalio.workflow.execute_activity(
                prepare_agent_run_activity,
                input,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if prepared.proceed:
                scout = await temporalio.workflow.execute_child_workflow(
                    RunSignalsScoutWorkflow.run,
                    RunSignalsScoutInput(
                        team_id=prepared.team_id,
                        skill_name=prepared.skill_name,
                        triggered_by=TRIGGERED_BY_AGENT_RUN,
                        run_note=prepared.run_note,
                        agent_run_id=input.run_id,
                    ),
                    id=prepared.scout_workflow_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    # The scout's own activity has this ceiling. The margin covers its queue time.
                    execution_timeout=timedelta(seconds=WORKFLOW_HARD_CEILING_S) + timedelta(minutes=15),
                )
                finish = FinishAgentRunInput(
                    run_id=input.run_id,
                    scout_run_id=scout.run_id,
                    scout_status=scout.status,
                    scout_skip_reason=scout.skip_reason,
                )
            elif prepared.outcome is None:
                return
            else:
                finish = FinishAgentRunInput(
                    run_id=input.run_id, outcome=prepared.outcome, reason_code=prepared.reason_code
                )
        except (ActivityError, ChildWorkflowError, WorkflowAlreadyStartedError):
            temporalio.workflow.logger.warning(
                "signals_agent_run: the pass did not complete", extra={"run_id": input.run_id}
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._finish(finish))
            raise
        await self._finish(finish)

    async def _finish(self, finish: FinishAgentRunInput) -> None:
        await temporalio.workflow.execute_activity(
            finish_agent_run_activity,
            finish,
            start_to_close_timeout=timedelta(minutes=2),
            schedule_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )


def agent_run_workflow_id(run_id: str) -> str:
    return f"signals-agent-run-{run_id}"


@async_to_sync
async def start_agent_run_workflow(run_id: str) -> str:
    """Start the workflow of one pass, and return its workflow id.

    The id comes from the row, so a second start for the same pass finds the first and starts nothing.
    """
    workflow_id = agent_run_workflow_id(run_id)
    client = await async_connect()
    try:
        await client.start_workflow(
            SignalsAgentRunWorkflow.run,
            AgentRunWorkflowInput(run_id=run_id),
            id=workflow_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except WorkflowAlreadyStartedError:
        pass
    return workflow_id
