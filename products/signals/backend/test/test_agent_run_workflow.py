import uuid
import logging
from datetime import timedelta

import pytest

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.scout_harness.limits import TRIGGERED_BY_AGENT_RUN
from products.signals.backend.temporal.agent_run import (
    AgentRunWorkflowInput,
    FinishAgentRunInput,
    PrepareAgentRunOutput,
    SignalsAgentRunWorkflow,
)
from products.signals.backend.temporal.agentic.scout_scheduler import RunSignalsScoutInput, RunSignalsScoutOutput

TASK_QUEUE = "test-agent-run-queue"
RUN_ID = "0199aaaa-0000-0000-0000-000000000001"

PROCEED = PrepareAgentRunOutput(
    proceed=True,
    team_id=1,
    skill_name="signals-scout-support-ticket",
    run_note="id: ticket-1",
    scout_workflow_id="scout-run-for-ticket-1",
)
BLOCKED = PrepareAgentRunOutput(proceed=False, outcome="blocked", reason_code="unsafe_content")
SETTLED = PrepareAgentRunOutput(proceed=False)
SCOUT_COMPLETED = RunSignalsScoutOutput(
    run_id="scout-1",
    task_run_id="task-run-1",
    status="completed",
    runtime_s=1.0,
    skill_name="signals-scout-support-ticket",
    skill_version=1,
)
SCOUT_SKIPPED = RunSignalsScoutOutput(
    run_id=None,
    task_run_id=None,
    status=None,
    runtime_s=0.0,
    skill_name="signals-scout-support-ticket",
    skill_version=1,
    skip_reason="quota_limited",
)
FAILED = FinishAgentRunInput(run_id=RUN_ID, outcome="failed", reason_code="agent_run_failed")


@workflow.defn(name="RunSignalsScoutWorkflow")
class _StubScoutWorkflow:
    @workflow.run
    async def run(self, input: RunSignalsScoutInput) -> RunSignalsScoutOutput:
        return await workflow.execute_activity(
            "stub_scout_run",
            input,
            result_type=RunSignalsScoutOutput,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prepared,scout,expected_finish",
    [
        pytest.param(
            BLOCKED,
            None,
            FinishAgentRunInput(run_id=RUN_ID, outcome="blocked", reason_code="unsafe_content"),
            id="blocked before the agent",
        ),
        pytest.param(
            PROCEED,
            SCOUT_COMPLETED,
            FinishAgentRunInput(run_id=RUN_ID, scout_run_id="scout-1", scout_status="completed"),
            id="the agent completed",
        ),
        pytest.param(
            PROCEED,
            SCOUT_SKIPPED,
            FinishAgentRunInput(run_id=RUN_ID, scout_skip_reason="quota_limited"),
            id="the scout run was skipped",
        ),
        pytest.param(PROCEED, None, FAILED, id="the agent's run crashed"),
        pytest.param(None, None, FAILED, id="prepare could not finish"),
        pytest.param(SETTLED, None, None, id="the pass is already settled"),
    ],
)
async def test_every_pass_that_started_ends_with_exactly_one_finish(
    prepared: PrepareAgentRunOutput | None,
    scout: RunSignalsScoutOutput | None,
    expected_finish: FinishAgentRunInput | None,
) -> None:
    scout_inputs: list[RunSignalsScoutInput] = []
    finishes: list[FinishAgentRunInput] = []

    @activity.defn(name="prepare_agent_run_activity")
    async def fake_prepare(_input: AgentRunWorkflowInput) -> PrepareAgentRunOutput:
        if prepared is None:
            raise ApplicationError("the safety model is down", non_retryable=True)
        return prepared

    @activity.defn(name="stub_scout_run")
    async def fake_scout_run(input: RunSignalsScoutInput) -> RunSignalsScoutOutput:
        scout_inputs.append(input)
        if scout is None:
            raise ApplicationError("the sandbox died", non_retryable=True)
        return scout

    @activity.defn(name="finish_agent_run_activity")
    async def fake_finish(input: FinishAgentRunInput) -> None:
        finishes.append(input)

    # A logging call with bad arguments wedges a workflow at INFO and is silent at the test default.
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalsAgentRunWorkflow, _StubScoutWorkflow],
            activities=[fake_prepare, fake_scout_run, fake_finish],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                SignalsAgentRunWorkflow.run,
                AgentRunWorkflowInput(run_id=RUN_ID),
                id=f"agent-run-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
                execution_timeout=timedelta(minutes=2),
            )

    assert finishes == ([expected_finish] if expected_finish is not None else [])
    assert [(input.triggered_by, input.agent_run_id, input.run_note) for input in scout_inputs] == (
        [(TRIGGERED_BY_AGENT_RUN, RUN_ID, "id: ticket-1")] if prepared is PROCEED else []
    )
