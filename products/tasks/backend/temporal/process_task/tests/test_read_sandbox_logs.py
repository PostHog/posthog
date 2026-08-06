from unittest.mock import MagicMock, patch

from products.tasks.backend.exceptions import SandboxNotRunningError
from products.tasks.backend.temporal.process_task.activities.read_sandbox_logs import (
    SANDBOX_TERMINATED_MESSAGE,
    ReadSandboxLogsInput,
    read_sandbox_logs,
)

_SANDBOX_PATH = "products.tasks.backend.temporal.process_task.activities.read_sandbox_logs.Sandbox"


def _run(sandbox_id: str, run_id: str | None = None) -> str:
    return read_sandbox_logs.__wrapped__(ReadSandboxLogsInput(sandbox_id=sandbox_id, run_id=run_id))  # type: ignore[attr-defined]


def test_returns_terminated_message_when_sandbox_not_running():
    sandbox = MagicMock()
    sandbox.is_running.return_value = False

    with patch(_SANDBOX_PATH) as mock_sandbox_cls:
        mock_sandbox_cls.get_by_id.return_value = sandbox
        result = _run("sb-gone")

    assert result == SANDBOX_TERMINATED_MESSAGE
    sandbox.execute.assert_not_called()


def test_returns_logs_when_running():
    sandbox = MagicMock()
    sandbox.is_running.return_value = True
    sandbox.execute.return_value = MagicMock(stdout="agent server log line")

    with patch(_SANDBOX_PATH) as mock_sandbox_cls:
        mock_sandbox_cls.get_by_id.return_value = sandbox
        result = _run("sb-running")

    assert "agent server log line" in result


def test_returns_terminated_message_on_mid_capture_termination():
    sandbox = MagicMock()
    sandbox.is_running.return_value = True
    sandbox.execute.side_effect = SandboxNotRunningError("gone", {"sandbox_id": "sb-race"}, cause=RuntimeError("gone"))

    with patch(_SANDBOX_PATH) as mock_sandbox_cls:
        mock_sandbox_cls.get_by_id.return_value = sandbox
        result = _run("sb-race")

    assert result == SANDBOX_TERMINATED_MESSAGE
