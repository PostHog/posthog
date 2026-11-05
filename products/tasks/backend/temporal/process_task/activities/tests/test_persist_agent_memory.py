from inspect import unwrap
from typing import Any

import pytest

from posthog.models import User
from posthog.storage.object_storage import ObjectStorageError

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


def _run(team: Any, state: dict) -> TaskRun:
    creator = User.objects.create_and_join(team.organization, "creator@example.com", None)
    task = Task.objects.create(team=team, title="Memory test", created_by=creator)
    return TaskRun.objects.create(team=team, task=task, state=state)


def _input(run: TaskRun, sandbox_id: str = "sb-1", actor_user_id: int | None = None) -> PersistAgentMemoryInput:
    return PersistAgentMemoryInput(
        sandbox_id=sandbox_id,
        run_id=str(run.id),
        team_id=run.team_id,
        user_id=7,
        reason="teardown",
        actor_user_id=actor_user_id,
    )


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
    run = _run(team, state)
    sandbox = _patch_sandbox(mocker, running=True)
    persist = mocker.patch(f"{MODULE}.persist_sandbox_memory", return_value=MemorySyncCounts(files_written=2))

    output = activity_environment.run(unwrap(persist_agent_memory), _input(run))

    persist.assert_called_once_with(sandbox, team_id=team.id, user_id=7, allow_deletes=expected_allow_deletes)
    assert output.error is None
    assert output.files_written == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "outcome, setup",
    [
        ("sandbox_not_running", "not_running"),
        ("unsupported", "no_file_listing"),
        ("actor_changed", "other_slack_actor"),
        ("actor_changed", "other_followup_actor"),
        ("persisted", "creator_followup_actor"),
    ],
)
def test_persist_outcome_for_each_run_condition(
    activity_environment: Any, mocker: Any, team: Any, outcome: str, setup: str
) -> None:
    state: dict[str, Any] = {}
    teammate = User.objects.create_and_join(team.organization, "teammate@example.com", None)
    if setup == "other_slack_actor":
        state = {"interaction_origin": "slack", "slack_actor_user_id": teammate.id}
    run = _run(team, state)
    actor_user_id = {"other_followup_actor": teammate.id, "creator_followup_actor": run.task.created_by_id}.get(setup)
    _patch_sandbox(mocker, running=setup != "not_running")
    persist = mocker.patch(f"{MODULE}.persist_sandbox_memory", return_value=MemorySyncCounts())
    if setup == "no_file_listing":
        persist.side_effect = NotImplementedError("HoglandSandbox does not support listing directories")

    output = activity_environment.run(unwrap(persist_agent_memory), _input(run, actor_user_id=actor_user_id))

    assert output.outcome == outcome
    assert persist.called is (outcome in ("persisted", "unsupported"))


@pytest.mark.django_db
def test_a_storage_failure_raises_so_temporal_retries(activity_environment: Any, mocker: Any, team: Any) -> None:
    run = _run(team, {})
    _patch_sandbox(mocker, running=True)
    mocker.patch(f"{MODULE}.persist_sandbox_memory", side_effect=ObjectStorageError("write failed"))

    with pytest.raises(ObjectStorageError):
        activity_environment.run(unwrap(persist_agent_memory), _input(run))


@pytest.mark.django_db
@pytest.mark.parametrize("complete", [True, False])
def test_only_a_complete_restore_marks_the_sandbox(mocker: Any, team: Any, complete: bool) -> None:
    run = _run(team, {AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY: "sb-previous"})
    sandbox = mocker.Mock(id="sb-1")
    mocker.patch(
        f"{MODULE}.restore_sandbox_memory",
        return_value=MemoryRestoreResult(counts=MemorySyncCounts(), complete=complete),
    )

    restore_agent_memory_into_sandbox(sandbox, run_id=str(run.id), team_id=team.id, user_id=7)

    run.refresh_from_db()
    assert run.state[AGENT_MEMORY_RESTORED_SANDBOX_STATE_KEY] == ("sb-1" if complete else "sb-previous")
