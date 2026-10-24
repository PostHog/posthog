import asyncio
import importlib
import threading
import contextlib

import pytest
from unittest.mock import MagicMock

from products.tasks.backend.exceptions import SandboxProvisionError
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities import provision_sandbox as provision_sandbox_module
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
    return [call.args[0].sandbox_id for call in cleanup.call_args_list]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_agent_start_failure_cleans_up_the_new_sandbox(task_context, boot_steps):
    boot_steps["start_agent_server_in_sandbox"].side_effect = RuntimeError("agent never became healthy")

    with pytest.raises(RuntimeError, match="agent never became healthy"):
        await boot_module._provision_sandbox_and_start_agent(
            ProvisionSandboxAndStartAgentInput(context=task_context), boot_module._CreationClock(60), threading.Event()
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
        ProvisionSandboxAndStartAgentInput(context=task_context), boot_module._CreationClock(60), threading.Event()
    )

    assert _cleaned_sandbox_ids(boot_steps["cleanup_sandbox_now"]) == ["sandbox-orphan"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cancelled_boot_cleans_up_the_sandbox_it_created(task_context, boot_steps, monkeypatch):
    monkeypatch.setattr(provision_sandbox_module.activity, "heartbeat", lambda: None)
    entered, release = threading.Event(), threading.Event()
    created = boot_steps["create_repository_sandbox"].return_value

    def blocked_create(_input):
        entered.set()
        release.wait(timeout=10)
        return created

    boot_steps["create_repository_sandbox"].side_effect = blocked_create
    boot = asyncio.create_task(
        boot_module.provision_sandbox_and_start_agent(ProvisionSandboxAndStartAgentInput(context=task_context))
    )
    await asyncio.to_thread(entered.wait, 10)
    boot.cancel()
    for _ in range(50):
        await asyncio.sleep(0.01)
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await boot

    assert _cleaned_sandbox_ids(boot_steps["cleanup_sandbox_now"]) == ["sandbox-new"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_timeout_raised_by_a_boot_step_fails_the_activity(task_context, boot_steps, monkeypatch):
    monkeypatch.setattr(provision_sandbox_module.activity, "heartbeat", lambda: None)
    boot_steps["start_agent_server_in_sandbox"].side_effect = TimeoutError("agent health wait")

    with pytest.raises(TimeoutError, match="agent health wait"):
        await asyncio.wait_for(
            boot_module.provision_sandbox_and_start_agent(ProvisionSandboxAndStartAgentInput(context=task_context)),
            timeout=30,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_creation_past_the_provider_deadline_fails_the_attempt(task_context, boot_steps, monkeypatch):
    monkeypatch.setattr(provision_sandbox_module.activity, "heartbeat", lambda: None)
    sandbox_class = MagicMock(creation_timeout_seconds=0)
    sandbox_class.creation_cancellation_scope.return_value = contextlib.nullcontext()
    monkeypatch.setattr(boot_module, "get_sandbox_class_for_run_backend", lambda _backend: sandbox_class)
    release = threading.Event()
    created = boot_steps["create_repository_sandbox"].return_value

    def hung_create(_input):
        release.wait(timeout=10)
        return created

    boot_steps["create_repository_sandbox"].side_effect = hung_create
    boot = asyncio.create_task(
        boot_module.provision_sandbox_and_start_agent(ProvisionSandboxAndStartAgentInput(context=task_context))
    )
    await asyncio.sleep(2)
    release.set()

    with pytest.raises(SandboxProvisionError):
        await boot
