import importlib
import threading

import pytest
from unittest.mock import MagicMock

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import CleanupSandboxInput
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
)
from products.tasks.backend.temporal.process_task.activities.provision_sandbox_and_start_agent import (
    ProvisionSandboxAndStartAgentInput,
)

boot_module = importlib.import_module(
    "products.tasks.backend.temporal.process_task.activities.provision_sandbox_and_start_agent"
)


@pytest.fixture
def boot_steps(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    prepared = PrepareSandboxForRepositoryOutput(
        sandbox_name="sandbox-name",
        repository=None,
        github_token="",
        branch=None,
        environment_variables={},
        snapshot_id=None,
        snapshot_external_id=None,
        used_snapshot=False,
        should_create_snapshot=True,
        shallow_clone=True,
        image_source="base_image",
        image_source_label="published sandbox base image",
    )
    created = CreateSandboxForRepositoryOutput(
        sandbox_id="sandbox-new", sandbox_url="https://sandbox.example", connect_token="connect-token"
    )
    steps = {
        "prepare_repository_sandbox": MagicMock(return_value=prepared),
        "create_repository_sandbox": MagicMock(return_value=(created, MagicMock())),
        "start_agent_server_in_sandbox": MagicMock(),
        "cleanup_sandbox_now": MagicMock(),
    }
    for name, mock in steps.items():
        monkeypatch.setattr(boot_module, name, mock)
    return steps


def _cleaned_sandbox_ids(cleanup: MagicMock) -> list[str]:
    return [call.args[0].sandbox_id for call in cleanup.call_args_list if isinstance(call.args[0], CleanupSandboxInput)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_agent_start_failure_cleans_up_the_new_sandbox(task_context, boot_steps):
    boot_steps["start_agent_server_in_sandbox"].side_effect = RuntimeError("agent never became healthy")

    with pytest.raises(RuntimeError, match="agent never became healthy"):
        await boot_module._provision_sandbox_and_start_agent(
            ProvisionSandboxAndStartAgentInput(context=task_context), threading.Event()
        )

    assert _cleaned_sandbox_ids(boot_steps["cleanup_sandbox_now"]) == ["sandbox-new"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retry_cleans_up_the_sandbox_a_crashed_attempt_left_behind(
    task_context, test_task_run, boot_steps, monkeypatch
):
    await TaskRun.objects.filter(id=test_task_run.id).aupdate(state={"sandbox_id": "sandbox-orphan"})
    monkeypatch.setattr(boot_module, "current_activity_attempt", lambda: 2)

    await boot_module._provision_sandbox_and_start_agent(
        ProvisionSandboxAndStartAgentInput(context=task_context), threading.Event()
    )

    assert _cleaned_sandbox_ids(boot_steps["cleanup_sandbox_now"]) == ["sandbox-orphan"]
