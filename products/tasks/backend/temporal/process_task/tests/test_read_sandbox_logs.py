import json

from unittest.mock import MagicMock, patch

from products.tasks.backend.exceptions import SandboxNotRunningError
from products.tasks.backend.logic.services.memory_watchdog import (
    MEMORY_WATCHDOG_EVENTS_SEPARATOR,
    MEMORY_WATCHDOG_NOW_PREFIX,
    MEMORY_WATCHDOG_STATE_SEPARATOR,
    build_memory_watchdog_read_command,
)
from products.tasks.backend.temporal.process_task.activities.read_sandbox_logs import (
    SANDBOX_TERMINATED_MESSAGE,
    ReadSandboxLogsInput,
    read_sandbox_logs,
)

_SANDBOX_PATH = (
    "products.tasks.backend.temporal.process_task.activities.read_sandbox_logs.get_sandbox_class_for_sandbox_id"
)


def _run(sandbox_id: str, run_id: str | None = None) -> str:
    return read_sandbox_logs.__wrapped__(ReadSandboxLogsInput(sandbox_id=sandbox_id, run_id=run_id))  # type: ignore[attr-defined]


def test_returns_terminated_message_when_sandbox_not_running():
    sandbox = MagicMock()
    sandbox.is_running.return_value = False

    with patch(_SANDBOX_PATH) as mock_sandbox_cls:
        mock_sandbox_cls.return_value.get_by_id.return_value = sandbox
        result = _run("sb-gone")

    assert result == SANDBOX_TERMINATED_MESSAGE
    sandbox.execute.assert_not_called()


def test_returns_logs_when_running():
    sandbox = MagicMock()
    sandbox.is_running.return_value = True
    sandbox.execute.return_value = MagicMock(stdout="agent server log line")

    with patch(_SANDBOX_PATH) as mock_sandbox_cls:
        mock_sandbox_cls.return_value.get_by_id.return_value = sandbox
        result = _run("sb-running")

    assert "agent server log line" in result


def test_returns_terminated_message_on_mid_capture_termination():
    sandbox = MagicMock()
    sandbox.is_running.return_value = True
    sandbox.execute.side_effect = SandboxNotRunningError("gone", {"sandbox_id": "sb-race"}, cause=RuntimeError("gone"))

    with patch(_SANDBOX_PATH) as mock_sandbox_cls:
        mock_sandbox_cls.return_value.get_by_id.return_value = sandbox
        result = _run("sb-race")

    assert result == SANDBOX_TERMINATED_MESSAGE


def test_reports_memory_watchdog_kills_to_metrics():
    gib = 1024**3
    watchdog_output = (
        f"{MEMORY_WATCHDOG_NOW_PREFIX}100\n{MEMORY_WATCHDOG_STATE_SEPARATOR}\n"
        f"{json.dumps({'ts': 99.0, 'source': 'cgroup_v1', 'peak_current': 15 * gib, 'limit': 16 * gib, 'kills': 3})}\n"
        f"{MEMORY_WATCHDOG_EVENTS_SEPARATOR}\n"
        f"{json.dumps({'event': 'kill', 'comm': 'bash', 'top_comm': 'vitest', 'tree_rss': 13 * gib, 'current': 14 * gib, 'limit': 16 * gib, 'signal': 'SIGTERM'})}\n"
    )
    sandbox = MagicMock()
    sandbox.is_running.return_value = True
    sandbox.execute.side_effect = lambda command, **_: MagicMock(
        stdout=watchdog_output if command == build_memory_watchdog_read_command() else ""
    )
    module = "products.tasks.backend.temporal.process_task.activities.read_sandbox_logs"

    with (
        patch(_SANDBOX_PATH) as mock_sandbox_cls,
        patch(f"{module}.increment_memory_watchdog_teardown") as increment_teardown,
        patch(f"{module}.increment_memory_watchdog_events") as increment_events,
    ):
        mock_sandbox_cls.return_value.get_by_id.return_value = sandbox
        _run("sb-running", run_id="run-1")

    increment_teardown.assert_called_once_with("alive")
    increment_events.assert_any_call("kill", 3)
