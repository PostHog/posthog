import uuid

import pytest

from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.read_agent_turn_state import ReadAgentTurnStateOutput
from products.tasks.backend.temporal.process_task.workflow import MAX_INACTIVITY_DEFERRALS, ProcessTaskWorkflow

pytestmark = [pytest.mark.asyncio]


def _workflow() -> ProcessTaskWorkflow:
    instance = ProcessTaskWorkflow()
    instance._context = TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        github_integration_id=1,
        repository="org/repo",
        distinct_id="user-1",
    )
    return instance


@pytest.mark.parametrize("turn_in_flight,expected", [(True, True), (False, False), (None, False)])
async def test_only_active_turns_defer(monkeypatch, turn_in_flight, expected):
    instance = _workflow()

    async def execute_activity(*args, **kwargs):
        return ReadAgentTurnStateOutput(turn_in_flight=turn_in_flight)

    monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", execute_activity)
    assert await instance._agent_is_mid_turn() is expected


async def test_deferral_budget_is_bounded(monkeypatch):
    instance = _workflow()

    async def execute_activity(*args, **kwargs):
        return ReadAgentTurnStateOutput(turn_in_flight=True)

    monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", execute_activity)

    results = [await instance._agent_is_mid_turn() for _ in range(MAX_INACTIVITY_DEFERRALS + 1)]
    assert results == [True] * MAX_INACTIVITY_DEFERRALS + [False]


async def test_activity_failure_does_not_defer(monkeypatch):
    instance = _workflow()

    async def execute_activity(*args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", execute_activity)
    assert await instance._agent_is_mid_turn() is False
