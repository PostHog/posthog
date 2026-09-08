from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock

from django.conf import settings

from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.subscriptions.backend import temporal
from products.subscriptions.backend.facade import outcomes as outcomes_facade
from products.subscriptions.backend.temporal import client, outcomes


def test_outcome_activity_passes_only_team_and_outcome_identifiers(monkeypatch) -> None:
    outcome_id = uuid4()
    calls: list[tuple[int, UUID]] = []

    def read_once(*, team_id: int, outcome_id: UUID) -> outcomes_facade.OutcomeReadResult:
        calls.append((team_id, outcome_id))
        return outcomes_facade.OutcomeReadResult(outcome_id=outcome_id, status="terminal", persisted=False)

    monkeypatch.setattr(outcomes_facade, "read_outcome_once", read_once)

    status = outcomes.read_proactive_outcome(
        outcomes.ProactiveOutcomeReadoutInput(team_id=17, outcome_id=outcome_id, due_at=datetime.now(UTC))
    )

    assert status == "terminal"
    assert calls == [(17, outcome_id)]


def test_outcome_temporal_registry_contains_one_workflow_and_activity() -> None:
    assert outcomes.WORKFLOWS == [outcomes.ReadProactiveOutcomeWorkflow]
    assert outcomes.ACTIVITIES == [outcomes.read_proactive_outcome]
    assert outcomes.ReadProactiveOutcomeWorkflow in temporal.WORKFLOWS
    assert outcomes.read_proactive_outcome in temporal.ACTIVITIES


@pytest.mark.parametrize("due_at", [datetime.now(UTC) + timedelta(days=7), datetime.now(UTC) - timedelta(seconds=1)])
def test_outcome_workflow_input_contains_only_the_durable_dispatch_contract(due_at: datetime) -> None:
    outcome_id = uuid4()

    input = outcomes.ProactiveOutcomeReadoutInput(team_id=17, outcome_id=outcome_id, due_at=due_at)

    assert input.team_id == 17
    assert input.outcome_id == outcome_id
    assert input.due_at == due_at


def test_starting_outcome_readout_uses_one_deterministic_workflow_id_and_analytics_queue(monkeypatch) -> None:
    temporal_client = AsyncMock()

    async def connect() -> AsyncMock:
        return temporal_client

    monkeypatch.setattr(client, "async_connect", connect)
    outcome_id = uuid4()
    due_at = datetime(2026, 9, 15, 12, tzinfo=UTC)

    client.start_proactive_outcome_readout(team_id=17, outcome_id=outcome_id, due_at=due_at)

    temporal_client.start_workflow.assert_awaited_once()
    workflow, input = temporal_client.start_workflow.await_args.args
    assert workflow == outcomes.PROACTIVE_OUTCOME_READOUT_WORKFLOW_NAME
    assert input == outcomes.ProactiveOutcomeReadoutInput(team_id=17, outcome_id=outcome_id, due_at=due_at)
    assert temporal_client.start_workflow.await_args.kwargs["id"] == f"proactive-outcome-{outcome_id}"
    assert temporal_client.start_workflow.await_args.kwargs["task_queue"] == settings.ANALYTICS_PLATFORM_TASK_QUEUE
    assert "id_reuse_policy" not in temporal_client.start_workflow.await_args.kwargs


def test_duplicate_outcome_readout_start_is_harmless(monkeypatch) -> None:
    outcome_id = uuid4()
    temporal_client = AsyncMock(
        start_workflow=AsyncMock(
            side_effect=WorkflowAlreadyStartedError(
                workflow_id=f"proactive-outcome-{outcome_id}",
                workflow_type=outcomes.PROACTIVE_OUTCOME_READOUT_WORKFLOW_NAME,
            )
        )
    )

    async def connect() -> AsyncMock:
        return temporal_client

    monkeypatch.setattr(client, "async_connect", connect)

    client.start_proactive_outcome_readout(team_id=17, outcome_id=outcome_id, due_at=datetime.now(UTC))

    temporal_client.start_workflow.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("due_offset", "terminal_status"),
    [
        (timedelta(days=7), "improved"),
        (-timedelta(seconds=1), "unavailable"),
    ],
)
async def test_outcome_workflow_time_skips_to_the_due_boundary_and_runs_one_readout(
    monkeypatch, due_offset: timedelta, terminal_status: str
) -> None:
    outcome_id = uuid4()
    calls: list[tuple[int, UUID]] = []

    def read_once(*, team_id: int, outcome_id: UUID) -> outcomes_facade.OutcomeReadResult:
        calls.append((team_id, outcome_id))
        return outcomes_facade.OutcomeReadResult(outcome_id=outcome_id, status=terminal_status, persisted=True)

    monkeypatch.setattr(outcomes_facade, "read_outcome_once", read_once)

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor() as activity_executor:
            async with Worker(
                environment.client,
                task_queue="proactive-outcome-test",
                workflows=[outcomes.ReadProactiveOutcomeWorkflow],
                activities=[outcomes.read_proactive_outcome],
                activity_executor=activity_executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await environment.client.execute_workflow(
                    outcomes.ReadProactiveOutcomeWorkflow.run,
                    outcomes.ProactiveOutcomeReadoutInput(
                        team_id=17,
                        outcome_id=outcome_id,
                        due_at=datetime.now(UTC) + due_offset,
                    ),
                    id=f"proactive-outcome-{outcome_id}",
                    task_queue="proactive-outcome-test",
                )

    assert result == terminal_status
    assert calls == [(17, outcome_id)]


@pytest.mark.asyncio
async def test_outcome_workflow_retries_a_transient_read_failure(monkeypatch) -> None:
    outcome_id = uuid4()
    attempts = 0

    def read_once(*, team_id: int, outcome_id: UUID) -> outcomes_facade.OutcomeReadResult:
        nonlocal attempts
        assert team_id == 17
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary outage")
        return outcomes_facade.OutcomeReadResult(outcome_id=outcome_id, status="improved", persisted=True)

    monkeypatch.setattr(outcomes_facade, "read_outcome_once", read_once)

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor() as activity_executor:
            async with Worker(
                environment.client,
                task_queue="proactive-outcome-retry-test",
                workflows=[outcomes.ReadProactiveOutcomeWorkflow],
                activities=[outcomes.read_proactive_outcome],
                activity_executor=activity_executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await environment.client.execute_workflow(
                    outcomes.ReadProactiveOutcomeWorkflow.run,
                    outcomes.ProactiveOutcomeReadoutInput(
                        team_id=17,
                        outcome_id=outcome_id,
                        due_at=datetime.now(UTC),
                    ),
                    id=f"proactive-outcome-retry-{outcome_id}",
                    task_queue="proactive-outcome-retry-test",
                )

    assert result == "improved"
    assert attempts == 2
