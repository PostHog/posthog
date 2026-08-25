import os
import sys
import socket
import asyncio

import pytest

from django.test import override_settings

from asgiref.sync import async_to_sync

from products.tasks.backend.exceptions import RepositoryCloneError
from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
from products.tasks.backend.logic.services.sandbox import ExecutionResult, Sandbox
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.metrics import modal_sandbox_backend_label, resume_mode_label
from products.tasks.backend.temporal.process_task.activities import provision_sandbox as provision_sandbox_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CloneRepositoryInSandboxInput,
    CreateSandboxForRepositoryInput,
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryOutput,
    _prepare_posthog_desktop_cloud_task,
    _sandbox_image_kind,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
)


def _context_for_desktop_bootstrap(
    *, image_name: str | None = "posthog-dev-stack", warm_enabled: bool = True
) -> TaskProcessingContext:
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
        desktop_workspace_warm_enabled=warm_enabled,
    )


def test_prepares_desktop_workspace_for_posthog_dev_stack_task(mocker):
    sandbox = mocker.Mock()
    sandbox.config.image_fallback = None
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)

    _prepare_posthog_desktop_cloud_task(
        _context_for_desktop_bootstrap(),
        sandbox,
        "PostHog/posthog",
    )

    sandbox.execute.assert_called_once_with(
        "cd /tmp/workspace/repos/posthog/posthog/products/desktop && pnpm bootstrap:cloud-task",
        timeout_seconds=10 * 60,
    )


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

    _prepare_posthog_desktop_cloud_task(
        _context_for_desktop_bootstrap(image_name=image_name),
        sandbox,
        repository,
    )

    sandbox.execute.assert_not_called()


def test_skips_desktop_workspace_preparation_when_warm_flag_is_off(mocker):
    sandbox = mocker.Mock()
    sandbox.config.image_fallback = None

    _prepare_posthog_desktop_cloud_task(
        _context_for_desktop_bootstrap(warm_enabled=False),
        sandbox,
        "posthog/posthog",
    )

    sandbox.execute.assert_not_called()


def test_desktop_workspace_preparation_failure_is_non_retryable(mocker):
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


@pytest.mark.parametrize(("value", "expected"), [(None, "v1"), ("0", "v1"), ("1", "v2")])
def test_modal_sandbox_backend_label(monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str) -> None:
    if value is None:
        monkeypatch.delenv("MODAL_SANDBOX_V2", raising=False)
    else:
        monkeypatch.setenv("MODAL_SANDBOX_V2", value)

    assert modal_sandbox_backend_label() == expected


@pytest.mark.parametrize(
    ("handoff_resumed", "using_modal_snapshot", "expected"),
    [
        (True, False, "handoff"),
        (True, True, "handoff_and_snapshot"),
        (False, True, "snapshot_only"),
        (False, False, "neither"),
    ],
)
def test_resume_mode_label(handoff_resumed: bool, using_modal_snapshot: bool, expected: str) -> None:
    assert resume_mode_label(handoff_resumed=handoff_resumed, using_modal_snapshot=using_modal_snapshot) == expected


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
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        state=state,
        _branch="feature-branch",
    )
    sandbox = mocker.Mock()
    sandbox.clone_repository.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.provision_sandbox.posthoganalytics.feature_enabled",
        return_value=True,
    )

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
        blobless=True,
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
            blobless=False,
        ),
        mocker.call(
            "posthog/posthog",
            github_token="github-token",
            shallow=True,
            branch=None,
            blobless=False,
        ),
    ]


def test_clone_failure_records_failed_latency_and_captures_command_result(mocker, activity_environment):
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=123,
        repository="posthog/posthog",
        distinct_id="distinct-id",
        state={},
    )
    sandbox = mocker.Mock()
    sandbox.clone_repository.return_value = ExecutionResult(
        stdout="clone output",
        stderr="",
        exit_code=124,
        error="execution stopped",
    )
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    metric_meter = mocker.patch("products.tasks.backend.temporal.metrics._metric_meter")
    capture_exception = mocker.patch("products.tasks.backend.exceptions.capture_exception")

    with pytest.raises(RepositoryCloneError) as error:
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

    assert "exit code 124" in str(error.value)
    assert error.value.context == {
        "repository": "posthog/posthog",
        "sandbox_id": "sandbox-id",
        "exit_code": 124,
        "stderr": "",
        "stdout": "clone output",
        "error": "execution stopped",
        "team": "array",
    }
    metric_meter.assert_called_once_with(
        {
            "step": "repository_clone",
            "used_snapshot": "false",
            "status": "FAILED",
            "runtime": "gvisor",
        }
    )
    assert str(capture_exception.call_args.args[0]) == "clone output"
