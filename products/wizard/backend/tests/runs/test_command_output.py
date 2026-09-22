import sys
import shlex
import subprocess
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from products.wizard.backend.logic.workers.commands import MAX_SANDBOX_LOG_BYTES, bound_command_output
from products.wizard.backend.logic.workers.repository_publisher import (
    RepositoryPublishingError,
    _run_git,
    _staged_changes,
)


@pytest.mark.parametrize("exit_code", [0, 7, 124])
def test_command_output_keeps_bounded_tails_and_exit_code(exit_code: int) -> None:
    script = (
        f"import sys; sys.stdout.write('a' * {MAX_SANDBOX_LOG_BYTES * 4} + 'out'); "
        f"sys.stderr.write('b' * {MAX_SANDBOX_LOG_BYTES * 4} + 'err'); sys.exit({exit_code})"
    )
    command = bound_command_output(f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}")
    result = subprocess.run(["bash", "-c", command], capture_output=True, timeout=10)
    assert result.returncode == exit_code
    assert result.stdout == b"a" * (MAX_SANDBOX_LOG_BYTES - 3) + b"out"
    assert result.stderr == b"b" * (MAX_SANDBOX_LOG_BYTES - 3) + b"err"


@pytest.mark.parametrize("size", [31, 32, 33, 100000])
def test_git_output_rejects_overflow_before_returning_contents(size: int) -> None:
    sandbox = MagicMock()

    def execute(command: str, *, timeout_seconds: int) -> SimpleNamespace:
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=timeout_seconds)
        assert len(result.stdout) <= 33
        return SimpleNamespace(stdout=result.stdout, exit_code=result.returncode)

    sandbox.execute.side_effect = execute
    arguments = f"--version >/dev/null; printf '%0{size}d' 0"
    if size > 32:
        with pytest.raises(RepositoryPublishingError, match="payload limit"):
            _run_git(sandbox, ".", arguments, "test", max_output_bytes=32)
    else:
        assert _run_git(sandbox, ".", arguments, "test", max_output_bytes=32) == "0" * size


@pytest.mark.parametrize("budget", [73, 74, 75])
def test_staged_changes_enforce_cumulative_encoded_budget(budget: int) -> None:
    sandbox = MagicMock()
    sandbox.execute.side_effect = [
        SimpleNamespace(stdout="A\0a\0A\0b\0", exit_code=0),
        SimpleNamespace(stdout="YQ==", exit_code=0),
        SimpleNamespace(stdout="Yg==", exit_code=0),
    ]
    with patch("products.wizard.backend.logic.workers.repository_publisher.MAX_COMMIT_PAYLOAD_BYTES", budget):
        if budget < 74:
            with pytest.raises(RepositoryPublishingError, match="payload limit"):
                _staged_changes(sandbox, ".", "HEAD")
        else:
            changes = _staged_changes(sandbox, ".", "HEAD")
            assert changes.additions == [("a", "YQ=="), ("b", "Yg==")]
            assert changes.deletions == []
