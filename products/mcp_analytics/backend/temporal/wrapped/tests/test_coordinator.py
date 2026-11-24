import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command

from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.exceptions import (
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models.team import Team

from products.mcp_analytics.backend.temporal.wrapped.activities import WrappedDiscoveryInputs, WrappedTeamInputs
from products.mcp_analytics.backend.temporal.wrapped.coordinator import (
    MCPWrappedCoordinatorWorkflow,
    WrappedCoordinatorInputs,
)

FAILING_TEAM_ID = 3
_discovered_years: list[int] = []
_generated_team_ids: list[int] = []
_error_to_raise: list[type[Exception]] = []


@activity.defn(name="discover_wrapped_team_ids_activity")
async def stub_discovery(inputs: WrappedDiscoveryInputs) -> list[int]:
    _discovered_years.append(inputs.year)
    return [1, 2, 3, 4, 5]


@activity.defn(name="generate_wrapped_activity")
async def stub_generate(inputs: WrappedTeamInputs) -> str:
    _generated_team_ids.append(inputs.team_id)
    if inputs.team_id == FAILING_TEAM_ID:
        raise ApplicationError("ClickHouse went away", non_retryable=True)
    return "ready" if inputs.team_id % 2 else "ineligible"


@activity.defn(name="generate_wrapped_activity")
async def stub_generate_raising(inputs: WrappedTeamInputs) -> str:
    _generated_team_ids.append(inputs.team_id)
    raise _error_to_raise[0]()


async def _run(inputs: WrappedCoordinatorInputs, generate: Any = stub_generate) -> dict[str, Any]:
    _discovered_years.clear()
    _generated_team_ids.clear()
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[MCPWrappedCoordinatorWorkflow],
            activities=[stub_discovery, generate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                MCPWrappedCoordinatorWorkflow.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
            )


@parameterized.expand([("one_run", 500), ("continues_as_new_between_runs", 2)])
async def test_one_failed_project_does_not_stop_the_others(_name: str, teams_per_run: int) -> None:
    result = await _run(WrappedCoordinatorInputs(year=2026, max_concurrent_teams=2, teams_per_run=teams_per_run))

    assert result == {
        "year": 2026,
        "teams": 5,
        "statuses": {"ready": 2, "ineligible": 2},
        "failed_team_ids": [FAILING_TEAM_ID],
    }


@parameterized.expand(
    [
        ("no_concurrency", WrappedCoordinatorInputs(year=2026, max_concurrent_teams=0)),
        ("negative_concurrency", WrappedCoordinatorInputs(year=2026, max_concurrent_teams=-1)),
        ("no_teams_per_run", WrappedCoordinatorInputs(year=2026, teams_per_run=0)),
    ]
)
async def test_invalid_limits_fail_before_any_work(_name: str, inputs: WrappedCoordinatorInputs) -> None:
    with pytest.raises(WorkflowFailureError):
        await _run(inputs)

    assert _discovered_years == []
    assert _generated_team_ids == []


@parameterized.expand(
    [
        ("query_timeout", ClickHouseQueryTimeOut, 1),
        ("estimated_too_slow", ClickHouseEstimatedQueryExecutionTimeTooLong, 1),
        ("query_memory_limit", ClickHouseQueryMemoryLimitExceeded, 1),
        ("cluster_memory_pressure", ClickHouseClusterMemoryLimitExceeded, 3),
        ("deleted_project", Team.DoesNotExist, 1),
    ]
)
async def test_only_transient_errors_are_retried(_name: str, error: type[Exception], attempts: int) -> None:
    _error_to_raise[:] = [error]

    result = await _run(WrappedCoordinatorInputs(year=2026, team_ids=[2]), generate=stub_generate_raising)

    assert _generated_team_ids == [2] * attempts
    assert result["failed_team_ids"] == [2]


async def test_chosen_projects_skip_discovery() -> None:
    result = await _run(WrappedCoordinatorInputs(year=2026, team_ids=[2, 2]))

    assert _discovered_years == []
    assert _generated_team_ids == [2]
    assert result["statuses"] == {"ineligible": 1}


async def test_without_a_year_the_run_covers_the_current_one() -> None:
    result = await _run(WrappedCoordinatorInputs())

    assert _discovered_years == [result["year"]] == [datetime.now(UTC).year]


@pytest.mark.django_db
def test_the_run_command_starts_the_coordinator() -> None:
    client = MagicMock()
    client.start_workflow = AsyncMock()

    with patch(
        "products.mcp_analytics.backend.management.commands.run_mcp_analytics_wrapped.async_connect",
        new=AsyncMock(return_value=client),
    ):
        call_command("run_mcp_analytics_wrapped", "--year", "2026", "--team-id", "2", "--team-id", "7")

    assert client.start_workflow.await_args.args == (
        "mcpa-wrapped-coordinator",
        WrappedCoordinatorInputs(year=2026, team_ids=[2, 7]),
    )
