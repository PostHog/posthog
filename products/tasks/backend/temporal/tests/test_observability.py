import pytest

from products.tasks.backend.exceptions import SandboxExecutionError
from products.tasks.backend.temporal.observability import FAILURE_REASON_MAX_CHARS, _diagnosed_failure_reason


def _sandbox_error(context: dict) -> SandboxExecutionError:
    return SandboxExecutionError(
        "Agent-server failed to start",
        context,
        cause=RuntimeError("health check failed after retries"),
        capture=False,
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            _sandbox_error({"sandbox_id": "sb-1", "failure_reason": "agent-server exited during startup: EADDRINUSE"}),
            "agent-server exited during startup: EADDRINUSE",
        ),
        (_sandbox_error({"sandbox_id": "sb-1"}), None),
        (RuntimeError("no context at all"), None),
    ],
    ids=["diagnosed_reason", "no_reason_diagnosed", "plain_exception"],
)
def test_diagnosed_failure_reason(error: BaseException, expected: str | None) -> None:
    assert _diagnosed_failure_reason(error) == expected


def test_diagnosed_failure_reason_is_bounded() -> None:
    error = _sandbox_error({"failure_reason": "x" * (FAILURE_REASON_MAX_CHARS * 3)})

    assert len(_diagnosed_failure_reason(error) or "") == FAILURE_REASON_MAX_CHARS
