import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.exceptions import SandboxExecutionError, SandboxNotFoundError
from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
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


def test_start_agent_server_launch_failure_is_captured(sandbox: DockerSandbox):
    failed = ExecutionResult(stdout="", stderr="boom", exit_code=1)
    with (
        patch.object(sandbox, "is_running", return_value=True),
        patch.object(sandbox, "write_file"),
        patch.object(sandbox, "_build_agent_server_command", return_value="run-agent-server"),
        patch.object(sandbox, "execute", return_value=failed),
        patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
        pytest.raises(SandboxExecutionError),
    ):
        sandbox.start_agent_server(repository=None, task_id="t1", run_id="r1", wait_for_health=False)

    # A genuine non-zero launch is a real fault — it still gets captured.
    capture_exception.assert_called_once()


def test_get_by_id_missing_container_is_not_captured():
    # `docker inspect` on a reaped/removed container exits non-zero. That's an expected
    # sandbox-lifecycle condition, so get_by_id must raise SandboxNotFoundError without a
    # subprocess cause — guarding against re-adding check=True (which would surface a raw
    # CalledProcessError) or reattaching the cause (which would capture it to error tracking).
    gone = MagicMock(stdout="", stderr="Error: No such object: gone", returncode=1)
    with (
        patch.object(DockerSandbox, "_run", return_value=gone),
        patch("products.tasks.backend.exceptions.capture_exception") as capture_exception,
        pytest.raises(SandboxNotFoundError),
    ):
        DockerSandbox.get_by_id("missing-sandbox-id")

    capture_exception.assert_not_called()
