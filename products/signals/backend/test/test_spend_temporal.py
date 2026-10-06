import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

import pytest

from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.dataclasses import frozen

from products.signals.backend.spend import current_spend_signal_id, signal_spend_scope, track_signal_spend
from products.signals.backend.temporal.grouping import GenerateSearchQueriesInput


@frozen
class SpendActivityResult:
    signal_id: str | None
    attempt: int


@activity.defn
@track_signal_spend
async def spend_probe_activity(input: GenerateSearchQueriesInput) -> SpendActivityResult:
    assert input.team_id is not None
    assert current_spend_signal_id(input.team_id) == input.signal_id
    if input.description == "retry" and activity.info().attempt == 1:
        raise ApplicationError("Retry the spend probe")
    return SpendActivityResult(
        signal_id=await sync_to_async(current_spend_signal_id)(input.team_id),
        attempt=activity.info().attempt,
    )


@activity.defn
async def unscoped_spend_probe_activity(team_id: int) -> str | None:
    return current_spend_signal_id(team_id)


@workflow.defn
class SpendScopeWorkflow:
    @workflow.run
    async def run(self, inputs: list[GenerateSearchQueriesInput]) -> list[SpendActivityResult]:
        team_id = inputs[0].team_id
        assert team_id is not None
        assert current_spend_signal_id(team_id) is None
        results = await asyncio.gather(
            *(
                workflow.execute_activity(
                    spend_probe_activity,
                    input,
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                for input in inputs
            )
        )
        assert current_spend_signal_id(team_id) is None
        assert (
            await workflow.execute_activity(
                unscoped_spend_probe_activity,
                team_id,
                start_to_close_timeout=timedelta(seconds=10),
            )
            is None
        )
        return results


@pytest.mark.asyncio
async def test_spend_scope_is_recreated_inside_each_activity(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    inputs = [
        GenerateSearchQueriesInput(
            team_id=1,
            signal_id=str(uuid4()),
            description=description,
            source_product="error_tracking",
            source_type="issue",
            signal_type_examples=[],
        )
        for description in ["retry", "success"]
    ]
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue="test-signal-spend",
            workflows=[SpendScopeWorkflow],
            activities=[spend_probe_activity, unscoped_spend_probe_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            caller_signal_id = str(uuid4())
            with signal_spend_scope(1, caller_signal_id, stage="caller"):
                results = await asyncio.wait_for(
                    env.client.execute_workflow(
                        SpendScopeWorkflow.run,
                        inputs,
                        id=str(uuid4()),
                        task_queue="test-signal-spend",
                        execution_timeout=timedelta(seconds=30),
                    ),
                    timeout=30,
                )
                assert current_spend_signal_id(1) == caller_signal_id

    assert results == [
        SpendActivityResult(signal_id=inputs[0].signal_id, attempt=2),
        SpendActivityResult(signal_id=inputs[1].signal_id, attempt=1),
    ]
    assert current_spend_signal_id(1) is None
