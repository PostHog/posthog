import re
import shlex

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX
from products.tasks.backend.exceptions import SandboxExecutionError
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


def test_build_agent_server_command_gates_exec_permission_regex(sandbox: DockerSandbox):
    with_flag = sandbox._build_agent_server_command(
        None, "t1", "r1", "interactive", True, posthog_exec_permission_regex=POSTHOG_EXEC_PERMISSION_REGEX
    )
    assert f"--posthogExecPermissionRegex {shlex.quote(POSTHOG_EXEC_PERMISSION_REGEX)}" in with_flag

    # An agent-server predating the flag rejects unknown options — the builder must omit it entirely.
    without_flag = sandbox._build_agent_server_command(None, "t1", "r1", "interactive", True)
    assert "--posthogExecPermissionRegex" not in without_flag


@parameterized.expand(
    [
        ("cdp-functions-partial-update", True),
        ("insight-update", True),
        ("survey-delete", True),
        ("dashboard-create", True),
        ("survey-launch", True),
        ("workflows-create-email-template", True),
        ("insight-create", False),
        ("cdp-functions-list", False),
        ("dashboard-create-extra", False),
    ]
)
def test_exec_permission_regex_matches_gated_sub_tools(sub_tool: str, should_match: bool):
    # The constant is hand-concatenated; a broken anchor or alternation silently stops relaying
    # approvals for (or starts prompting on) the wrong sub-tools.
    assert bool(re.search(POSTHOG_EXEC_PERMISSION_REGEX, sub_tool, re.IGNORECASE)) is should_match


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
