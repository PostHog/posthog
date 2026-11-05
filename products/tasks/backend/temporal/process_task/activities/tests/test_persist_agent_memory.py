from inspect import unwrap
from typing import Any

import pytest

from products.tasks.backend.logic.services.agent_memory import MemoryRestoreResult, MemorySyncCounts
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.persist_agent_memory import (
    AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY,
    PersistAgentMemoryInput,
    persist_agent_memory,
    restore_agent_memory_into_sandbox,
)

MODULE = "products.tasks.backend.temporal.process_task.activities.persist_agent_memory"


def _patch_sandbox(mocker: Any, *, running: bool) -> Any:
    sandbox = mocker.Mock()
    sandbox.is_running.return_value = running
    sandbox_class = mocker.Mock()
    sandbox_class.get_by_id.return_value = sandbox
    mocker.patch(f"{MODULE}.get_sandbox_class_for_sandbox_id", return_value=sandbox_class)
    return sandbox


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state, expected_allow_deletes",
    [
        ({AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY: "sb-1"}, True),
        ({AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY: "sb-previous"}, False),
        ({}, False),
    ],
)
def test_persist_deletes_only_from_the_sandbox_that_received_a_complete_restore(
    activity_environment: Any, mocker: Any, team: Any, state: dict, expected_allow_deletes: bool
) -> None:
    task = Task.objects.create(team=team, title="Memory test")
    run = TaskRun.objects.create(team=team, task=task, state=state)
    sandbox = _patch_sandbox(mocker, running=True)
    persist = mocker.patch(f"{MODULE}.persist_sandbox_memory", return_value=MemorySyncCounts(files_written=2))

    output = activity_environment.run(
        unwrap(persist_agent_memory),
        PersistAgentMemoryInput(sandbox_id="sb-1", run_id=str(run.id), team_id=team.id, user_id=7, reason="teardown"),
    )

    persist.assert_called_once_with(sandbox, user_id=7, allow_deletes=expected_allow_deletes)
    assert output.error is None
    assert output.files_written == 2


def test_persist_returns_an_error_without_raising_when_the_sandbox_is_gone(
    activity_environment: Any, mocker: Any
) -> None:
    _patch_sandbox(mocker, running=False)
    persist = mocker.patch(f"{MODULE}.persist_sandbox_memory")

    output = activity_environment.run(
        unwrap(persist_agent_memory),
        PersistAgentMemoryInput(sandbox_id="sb-1", run_id="run-1", team_id=1, user_id=7, reason="teardown"),
    )

    persist.assert_not_called()
    assert output.error == "Sandbox not running"


@pytest.mark.django_db
@pytest.mark.parametrize("complete", [True, False])
def test_only_a_complete_restore_marks_the_sandbox(mocker: Any, team: Any, complete: bool) -> None:
    task = Task.objects.create(team=team, title="Memory test")
    run = TaskRun.objects.create(team=team, task=task, state={AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY: "sb-previous"})
    sandbox = mocker.Mock(id="sb-1")
    mocker.patch(
        f"{MODULE}.restore_sandbox_memory",
        return_value=MemoryRestoreResult(counts=MemorySyncCounts(), complete=complete),
    )

    restore_agent_memory_into_sandbox(sandbox, run_id=str(run.id), user_id=7)

    run.refresh_from_db()
    assert run.state[AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY] == ("sb-1" if complete else "sb-previous")


@pytest.mark.django_db
def test_a_backend_without_file_listing_is_not_reported_as_a_failed_persist(
    activity_environment: Any, mocker: Any, team: Any
) -> None:
    task = Task.objects.create(team=team, title="Memory test")
    run = TaskRun.objects.create(team=team, task=task, state={})
    sandbox = _patch_sandbox(mocker, running=True)
    sandbox.list_dir.side_effect = NotImplementedError("HoglandSandbox does not support listing directories")
    sync_outcomes = mocker.patch(f"{MODULE}.increment_agent_memory_sync")

    output = activity_environment.run(
        unwrap(persist_agent_memory),
        PersistAgentMemoryInput(sandbox_id="box-1", run_id=str(run.id), team_id=team.id, user_id=7, reason="teardown"),
    )

    assert output.error is None
    sync_outcomes.assert_called_once_with("persist", "unsupported")
