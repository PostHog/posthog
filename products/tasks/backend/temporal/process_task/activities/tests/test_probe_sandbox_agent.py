import asyncio
import importlib

import pytest
from unittest.mock import Mock

from temporalio.testing import ActivityEnvironment

from products.tasks.backend.exceptions import SandboxNotFoundError, SandboxNotRunningError
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.probe_sandbox_agent import (
    ProbeSandboxAgentInput,
    probe_sandbox_agent,
)


def _sandbox(*, running: bool = True, execute=None) -> Mock:
    sandbox = Mock()
    sandbox.is_running.return_value = running
    sandbox.agent_server_health_url.return_value = "http://127.0.0.1:8080/health"
    if isinstance(execute, Exception):
        sandbox.execute.side_effect = execute
    else:
        sandbox.execute.return_value = execute
    return sandbox


def _sandbox_class(sandbox=None, *, get_error: Exception | None = None) -> Mock:
    sandbox_class = Mock()
    if get_error is not None:
        sandbox_class.get_by_id.side_effect = get_error
    else:
        sandbox_class.get_by_id.return_value = sandbox
    return sandbox_class


@pytest.mark.parametrize(
    "sandbox_class, expected_responsive, expected_reason",
    [
        (
            _sandbox_class(get_error=SandboxNotFoundError("missing", {"sandbox_id": "sb-1"}, RuntimeError("missing"))),
            False,
            "sandbox_not_found",
        ),
        (_sandbox_class(_sandbox(running=False)), False, "sandbox_not_running"),
        (
            _sandbox_class(_sandbox(execute=ExecutionResult(stdout="ok", stderr="", exit_code=0))),
            True,
            "agent_server_healthy",
        ),
        (
            _sandbox_class(_sandbox(execute=ExecutionResult(stdout="", stderr="", exit_code=7))),
            False,
            "agent_server_unhealthy:7",
        ),
        (
            _sandbox_class(
                _sandbox(execute=SandboxNotRunningError("stopped", {"sandbox_id": "sb-1"}, RuntimeError("stopped")))
            ),
            False,
            "sandbox_not_running",
        ),
        (_sandbox_class(_sandbox(execute=TimeoutError("hung"))), False, "probe_failed:TimeoutError"),
    ],
)
def test_probe_reports_whether_the_agent_server_answers(
    monkeypatch, sandbox_class, expected_responsive, expected_reason
):
    module = importlib.import_module("products.tasks.backend.temporal.process_task.activities.probe_sandbox_agent")
    monkeypatch.setattr(module, "get_sandbox_class_for_sandbox_id", Mock(return_value=sandbox_class))

    output = asyncio.run(
        ActivityEnvironment().run(probe_sandbox_agent, ProbeSandboxAgentInput(sandbox_id="sb-1", run_id="run-1"))
    )

    assert (output.responsive, output.reason) == (expected_responsive, expected_reason)
