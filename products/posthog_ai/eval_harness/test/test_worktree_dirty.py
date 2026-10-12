import subprocess

from unittest.mock import patch

from parameterized import parameterized

from products.posthog_ai.eval_harness.harness.lifecycle import _worktree_dirty


@parameterized.expand(
    [
        ("clean", subprocess.CompletedProcess([], 0, stdout=""), False),
        ("modified", subprocess.CompletedProcess([], 0, stdout=" M products/x.py\n"), True),
        ("git_failed", subprocess.CalledProcessError(128, "git"), None),
        ("git_slow", subprocess.TimeoutExpired("git", 10), None),
        ("git_missing", FileNotFoundError("git"), None),
    ]
)
def test_worktree_dirty(_name: str, outcome: object, expected: bool | None) -> None:
    with patch("products.posthog_ai.eval_harness.harness.lifecycle.subprocess.run") as run:
        if isinstance(outcome, BaseException):
            run.side_effect = outcome
        else:
            run.return_value = outcome
        assert _worktree_dirty() is expected
