import shlex

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX
from products.tasks.backend.exceptions import SandboxExecutionError
from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
from products.tasks.backend.logic.services.local_skills import ENV_DISABLE_BUNDLED_SKILLS
from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxConfig


@pytest.fixture
def sandbox() -> DockerSandbox:
    config = SandboxConfig(name="test-sandbox")
    return DockerSandbox(container_id="c" * 64, config=config, host_port=8000)


def _log_result() -> ExecutionResult:
    return ExecutionResult(stdout="agent-server log", stderr="", exit_code=0)


def test_wait_for_agent_server_ready_timeout_is_retryable_and_not_captured(sandbox: DockerSandbox):
    with (
        patch.object(sandbox, "_wait_for_health_check", return_value=False),
        patch.object(sandbox, "execute", return_value=_log_result()),
        patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
        pytest.raises(SandboxExecutionError) as exc,
    ):
        sandbox.wait_for_agent_server_ready()

    # Transient health-check timeout Temporal retries — retryable, and no error-tracking issue.
    assert exc.value.non_retryable is False
    capture_exception.assert_not_called()


def test_start_agent_server_health_check_timeout_is_retryable_and_not_captured(sandbox: DockerSandbox):
    with (
        patch.object(sandbox, "is_running", return_value=True),
        patch.object(sandbox, "write_file"),
        patch.object(sandbox, "_build_agent_server_command", return_value="run-agent-server"),
        patch.object(sandbox, "_launch_and_check", return_value=False),
        patch.object(sandbox, "execute", return_value=_log_result()),
        patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
        pytest.raises(SandboxExecutionError) as exc,
    ):
        sandbox.start_agent_server(repository=None, task_id="t1", run_id="r1")

    assert exc.value.non_retryable is False
    capture_exception.assert_not_called()


def test_docker_sandbox_does_not_combine_agent_server_start_and_health(sandbox: DockerSandbox):
    assert sandbox.supports_combined_agent_server_start_and_health() is False


def test_read_agent_server_boot_metrics_includes_process_milestones(sandbox: DockerSandbox):
    response = ExecutionResult(
        stdout='{"sessionInitMs":90,"boot":{"totalMs":140,"httpReadyMs":12,"launcherToProcessMs":8,"phasesMs":{"context_fetch":40,"secret":1}}}',
        stderr="",
        exit_code=0,
    )
    with patch.object(sandbox, "execute", return_value=response):
        assert sandbox.read_agent_server_boot_metrics() == (
            90,
            {"context_fetch": 40, "server_total": 140, "http_ready": 12, "launcher_to_process": 8},
        )


def test_read_agent_server_boot_metrics_uses_pi_boot_total(sandbox: DockerSandbox):
    response = ExecutionResult(stdout='{"sessionInitMs":90,"bootMs":140}', stderr="", exit_code=0)
    with patch.object(sandbox, "execute", return_value=response):
        assert sandbox.read_agent_server_boot_metrics() == (90, {"server_total": 140})


def test_build_agent_server_command_gates_connected_project_operations(sandbox: DockerSandbox):
    with_flag = sandbox._build_agent_server_command(
        None, "t1", "r1", "interactive", True, posthog_exec_permission_regex=POSTHOG_EXEC_PERMISSION_REGEX
    )
    assert f"--posthogExecPermissionRegex {shlex.quote(POSTHOG_EXEC_PERMISSION_REGEX)}" in with_flag

    without_flag = sandbox._build_agent_server_command(None, "t1", "r1", "interactive", True)
    assert "--posthogExecPermissionRegex" not in without_flag


def test_start_agent_server_launch_failure_is_captured(sandbox: DockerSandbox):
    failed = ExecutionResult(stdout="", stderr="boom", exit_code=1)

    def execute(command: str, **kwargs) -> ExecutionResult:
        # Only the launch fails; the bundled-skills clear that precedes it succeeds.
        if ENV_DISABLE_BUNDLED_SKILLS in command:
            return ExecutionResult(stdout="", stderr="", exit_code=0)
        return failed

    with (
        patch.object(sandbox, "is_running", return_value=True),
        patch.object(sandbox, "write_file"),
        patch.object(sandbox, "_build_agent_server_command", return_value="run-agent-server") as build_command,
        patch.object(sandbox, "agent_server_supports_exec_permission_regex", return_value=True),
        patch.object(sandbox, "execute", side_effect=execute),
        patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
        pytest.raises(SandboxExecutionError),
    ):
        sandbox.start_agent_server(repository=None, task_id="t1", run_id="r1", wait_for_health=False)

    # A genuine non-zero launch is a real fault — it still gets captured.
    capture_exception.assert_called_once()
    assert build_command.call_args.kwargs["posthog_exec_permission_regex"] == POSTHOG_EXEC_PERMISSION_REGEX


@parameterized.expand([("empty", b""), ("with_content", b"GITHUB_TOKEN=ghs_x\x00")])
def test_write_file_creates_the_temp_file_before_moving_it(_name: str, payload: bytes):
    # Blanking a credential file writes an empty payload. Chunking over an empty string produces
    # no writes at all, so the mv would rename a temp path that was never created.
    config = SandboxConfig(name="test-sandbox")
    sandbox = DockerSandbox(container_id="c" * 64, config=config, host_port=8000)
    commands: list[str] = []

    def _record(command: str, **kwargs) -> ExecutionResult:
        commands.append(command)
        return ExecutionResult(stdout="", stderr="", exit_code=0)

    with patch.object(sandbox, "is_running", return_value=True), patch.object(sandbox, "execute", side_effect=_record):
        result = sandbox.write_file("/tmp/creds.env", payload)

    assert result.exit_code == 0
    assert any("EOF_SANDBOX_WRITE" in command for command in commands), "temp file was never written"
    assert commands[-1].startswith("mv ")
