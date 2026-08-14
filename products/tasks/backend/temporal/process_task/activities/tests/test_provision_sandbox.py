import os
import sys
import socket
import asyncio

import pytest

from django.test import override_settings

from asgiref.sync import async_to_sync

from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
from products.tasks.backend.logic.services.sandbox import ExecutionResult, Sandbox
from products.tasks.backend.temporal.process_task.activities import provision_sandbox as provision_sandbox_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    AwaitDesktopWorkspacePreparationInput,
    CloneRepositoryInSandboxInput,
    CreateSandboxForRepositoryInput,
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
    _prepare_posthog_desktop_cloud_task,
    _sandbox_image_kind,
    await_desktop_workspace_preparation,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
)


def _context_for_desktop_bootstrap(*, image_name: str | None = "posthog-dev-stack") -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=123,
        repository="posthog/posthog",
        distinct_id="distinct-id",
        state={},
        custom_image_name=image_name,
    )


def test_prepares_desktop_workspace_for_posthog_dev_stack_task(mocker):
    sandbox = mocker.Mock()
    sandbox.config.image_fallback = None
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)

    started = _prepare_posthog_desktop_cloud_task(
        _context_for_desktop_bootstrap(),
        sandbox,
        "PostHog/posthog",
    )

    assert started is True
    sandbox.execute.assert_called_once()
    command = sandbox.execute.call_args.args[0]
    assert command.startswith("touch /tmp/workspace/.agent-credentials /tmp/workspace/.agent-credentials.tmp && ")
    assert "nohup /bin/sh -c" in command
    assert "/usr/bin/unshare --mount --pid --net --fork" in command
    assert "/usr/bin/setpriv --bounding-set=-all" in command
    assert "/usr/bin/env -i" in command
    assert "/usr/bin/mount --make-rprivate /" in command
    assert "/usr/bin/mount -t tmpfs tmpfs /mnt" in command
    assert (
        "mount --bind /tmp/workspace/repos/posthog/posthog/products/desktop /mnt/posthog-desktop-workspace" in command
    )
    assert "/usr/bin/mount -t tmpfs tmpfs /tmp" in command
    assert (
        "mount --bind /mnt/posthog-desktop-workspace /tmp/workspace/repos/posthog/posthog/products/desktop" in command
    )
    assert "/usr/bin/findmnt -rn -o TARGET" in command
    assert '/usr/bin/mount -o remount,bind,ro "$target"' in command
    assert 'case "$target" in /tmp|/tmp/*|/mnt|/mnt/*)' in command
    assert "/tmp/desktop-workspace-bootstrap/scratch" in command
    assert "mount --bind /dev/null /tmp/workspace/.agent-credentials" not in command
    assert "/run/systemd/private /run/dbus/system_bus_socket /var/run/docker.sock" in command
    assert "mkdir /tmp/desktop-workspace-bootstrap" in command
    assert "pnpm fetch" not in command
    assert "PNPM_CONFIG_OFFLINE=true" in command
    assert "pnpm bootstrap:cloud-task" in command
    assert "/tmp/desktop-workspace-bootstrap/status" in command
    assert command.index("/usr/bin/unshare") < command.index("printf")
    assert sandbox.execute.call_args.kwargs == {"timeout_seconds": 30}


@pytest.mark.parametrize(
    "image_name, repository, image_fallback",
    [
        (None, "posthog/posthog", None),
        ("team-image", "posthog/posthog", None),
        ("posthog-dev-stack", "posthog/posthog-js", None),
        ("posthog-dev-stack", "posthog/posthog", "custom image -> base image"),
    ],
)
def test_skips_desktop_workspace_preparation_for_other_images_repositories_and_fallbacks(
    mocker, image_name, repository, image_fallback
):
    sandbox = mocker.Mock()
    sandbox.config.image_fallback = image_fallback

    started = _prepare_posthog_desktop_cloud_task(
        _context_for_desktop_bootstrap(image_name=image_name),
        sandbox,
        repository,
    )

    assert started is False
    sandbox.execute.assert_not_called()


def test_desktop_workspace_preparation_launch_failure_is_non_retryable(mocker):
    from temporalio.exceptions import ApplicationError

    sandbox = mocker.Mock()
    sandbox.config.image_fallback = None
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="build failed", exit_code=1)

    with pytest.raises(ApplicationError) as error:
        _prepare_posthog_desktop_cloud_task(
            _context_for_desktop_bootstrap(),
            sandbox,
            "posthog/posthog",
        )

    assert error.value.non_retryable is True
    assert "build failed" in str(error.value)


def test_awaits_desktop_workspace_preparation(mocker, activity_environment):
    sandbox = mocker.Mock()
    sandbox.execute.side_effect = [
        ExecutionResult(stdout="pending\n", stderr="", exit_code=0),
        ExecutionResult(stdout="0\n", stderr="", exit_code=0),
    ]
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    mocker.patch.object(provision_sandbox_module, "emit_agent_log")
    heartbeat = mocker.patch.object(provision_sandbox_module.activity, "heartbeat")
    sleep = mocker.patch.object(provision_sandbox_module.time, "sleep")

    async_to_sync(activity_environment.run)(
        await_desktop_workspace_preparation,
        AwaitDesktopWorkspacePreparationInput(
            context=_context_for_desktop_bootstrap(),
            sandbox_id="sandbox-id",
        ),
    )

    command = sandbox.execute.call_args_list[0].args[0]
    assert "if [ -f /tmp/desktop-workspace-bootstrap/status ]" in command
    assert "echo pending" in command
    assert sandbox.execute.call_args_list[0].kwargs == {"timeout_seconds": 5}
    heartbeat.assert_called_once_with()
    sleep.assert_called_once_with(provision_sandbox_module._DESKTOP_BOOTSTRAP_POLL_INTERVAL_SECONDS)


def test_desktop_workspace_preparation_failure_includes_background_log(mocker, activity_environment):
    from temporalio.exceptions import ApplicationError

    sandbox = mocker.Mock()
    sandbox.execute.side_effect = [
        ExecutionResult(stdout="", stderr="bootstrap failed", exit_code=1),
        ExecutionResult(stdout="build failed", stderr="", exit_code=0),
    ]
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    mocker.patch.object(provision_sandbox_module, "emit_agent_log")

    with pytest.raises(ApplicationError) as error:
        async_to_sync(activity_environment.run)(
            await_desktop_workspace_preparation,
            AwaitDesktopWorkspacePreparationInput(
                context=_context_for_desktop_bootstrap(),
                sandbox_id="sandbox-id",
            ),
        )

    assert error.value.non_retryable is True
    assert "build failed" in str(error.value)


@pytest.mark.parametrize(
    "image_source, custom_image_name, expected",
    [
        ("custom_image", "posthog-dev-stack", "dev_stack"),
        ("custom_image", "team-image", "custom"),
        ("resume_snapshot", "posthog-dev-stack", "resume_snapshot"),
        ("repository_snapshot", None, "repository_snapshot"),
        ("base_image", None, "base"),
    ],
)
def test_sandbox_image_kind(image_source: str, custom_image_name: str | None, expected: str) -> None:
    assert _sandbox_image_kind(image_source, custom_image_name) == expected


@pytest.mark.asyncio
@override_settings(SANDBOX_PROVIDER="docker")
async def test_create_sandbox_cancellation_stops_docker_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provision_sandbox_module.activity, "heartbeat", lambda: None)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)
        port = server.getsockname()[1]
        command = [
            sys.executable,
            "-c",
            (
                "import os, socket, threading; "
                f"client = socket.create_connection(('127.0.0.1', {port})); "
                "client.sendall(f'{os.getpid()}\\n'.encode()); "
                "threading.Event().wait()"
            ),
        ]

        async def run_docker_subprocess(_input: CreateSandboxForRepositoryInput) -> CreateSandboxForRepositoryOutput:
            await asyncio.to_thread(DockerSandbox._run, command)
            raise AssertionError("cancelled Docker subprocess returned")

        monkeypatch.setattr(provision_sandbox_module, "_create_sandbox_for_repository", run_docker_subprocess)
        input = CreateSandboxForRepositoryInput(
            context=TaskProcessingContext(
                task_id="task-id",
                run_id="run-id",
                team_id=1,
                team_uuid="team-uuid",
                organization_id="organization-id",
                github_integration_id=None,
                repository=None,
                distinct_id="distinct-id",
                state={},
            ),
            prepared=PrepareSandboxForRepositoryOutput(
                sandbox_name="task-sandbox-task-id",
                repository=None,
                github_token="",
                branch=None,
                environment_variables={},
                snapshot_id=None,
                snapshot_external_id=None,
                used_snapshot=False,
                should_create_snapshot=True,
                shallow_clone=True,
                image_source="docker_base_image",
                image_source_label="local Docker sandbox image",
            ),
        )

        activity_task = asyncio.create_task(create_sandbox_for_repository(input))
        connection, _ = await asyncio.to_thread(server.accept)
        with connection, connection.makefile("r") as stream:
            child_pid = int(await asyncio.to_thread(stream.readline))

        activity_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await activity_task

    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.parametrize(
    "state, expected_branch",
    [
        ({"resume_from_run_id": "previous-run-id"}, "feature-branch"),
        ({"handoff_resumed": True}, "feature-branch"),
        ({}, None),
    ],
)
def test_clone_repository_uses_saved_branch_only_for_resumes(mocker, activity_environment, state, expected_branch):
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=123,
        repository="posthog/posthog",
        distinct_id="distinct-id",
        state=state,
        _branch="feature-branch",
    )
    sandbox = mocker.Mock()
    sandbox.clone_repository.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(
        clone_repository_in_sandbox,
        CloneRepositoryInSandboxInput(
            context=context,
            sandbox_id="sandbox-id",
            repository="posthog/posthog",
            github_token="github-token",
            shallow_clone=True,
        ),
    )

    sandbox.clone_repository.assert_called_once_with(
        "posthog/posthog",
        github_token="github-token",
        shallow=True,
        branch=expected_branch,
    )


def test_resume_clone_falls_back_to_default_branch_when_saved_branch_is_missing(mocker, activity_environment):
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=123,
        repository="posthog/posthog",
        distinct_id="distinct-id",
        state={"resume_from_run_id": "previous-run-id"},
        _branch="branch-from-a-sibling-repository",
    )
    sandbox = mocker.Mock()
    sandbox.clone_repository.side_effect = [
        ExecutionResult(
            stdout="",
            stderr=(
                "warning: Could not find remote branch branch-from-a-sibling-repository to clone.\n"
                "fatal: Remote branch branch-from-a-sibling-repository not found in upstream origin"
            ),
            exit_code=128,
        ),
        ExecutionResult(stdout="", stderr="", exit_code=0),
    ]
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(
        clone_repository_in_sandbox,
        CloneRepositoryInSandboxInput(
            context=context,
            sandbox_id="sandbox-id",
            repository="posthog/posthog",
            github_token="github-token",
            shallow_clone=True,
        ),
    )

    assert sandbox.clone_repository.call_args_list == [
        mocker.call(
            "posthog/posthog",
            github_token="github-token",
            shallow=True,
            branch="branch-from-a-sibling-repository",
        ),
        mocker.call(
            "posthog/posthog",
            github_token="github-token",
            shallow=True,
            branch=None,
        ),
    ]
