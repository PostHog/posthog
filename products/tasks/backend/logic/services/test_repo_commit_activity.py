import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.tasks.backend.logic.services.repo_commit_activity import (
    RepositoryCommitActivityError,
    _parse_log,
    collect_repository_commit_activity,
)
from products.tasks.backend.logic.services.sandbox import ExecutionResult

_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40


def test_parse_log_extracts_commits_with_paths():
    stdout = (
        f"\x01{_SHA_A}\x1f2026-07-10T10:00:00+00:00\n"
        "products/signals/backend/models.py\n"
        "products/signals/backend/tasks.py\n"
        f"\x01{_SHA_B}\x1f2026-07-01T09:00:00+00:00\n"
        "posthog/models/user.py\n"
    )

    commits = _parse_log(stdout)

    assert [c.sha for c in commits] == [_SHA_A, _SHA_B]
    assert commits[0].paths == [
        "products/signals/backend/models.py",
        "products/signals/backend/tasks.py",
    ]
    assert commits[1].committed_at == "2026-07-01T09:00:00+00:00"


def test_parse_log_skips_malformed_records_and_handles_empty_output():
    assert _parse_log("") == []
    assert _parse_log("\x01broken-header-without-separators\nsome/path.py\n") == []
    # Shape validation: non-hex sha and non-ISO date records are dropped, so free-text
    # fields can't forge a record even if they smuggle the delimiters in.
    assert _parse_log("\x01not-a-sha\x1f2026-07-05T08:00:00+00:00\npath.py\n") == []
    assert _parse_log(f"\x01{_SHA_C}\x1fyesterday\npath.py\n") == []

    commits = _parse_log(f"\x01{_SHA_C}\x1f2026-07-05T08:00:00+00:00\n")
    assert len(commits) == 1
    assert commits[0].paths == []


_TOKEN = "ghs_fake_token_value"
_SHALLOW_INFO_FAILURE = ExecutionResult(
    stdout="", stderr=f"fatal: error processing shallow info: 4 for {_TOKEN}", exit_code=128
)
_OK = ExecutionResult(stdout="", stderr="", exit_code=0)


class _FakeSandbox:
    id = "sandbox-1"

    def __init__(self, shallow_clone: ExecutionResult, tip_probe: ExecutionResult | None = None) -> None:
        self.shallow_clone = shallow_clone
        self.tip_probe = tip_probe
        self.commands: list[str] = []
        self.destroyed = False

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        self.commands.append(command)
        if "--shallow-since" in command:
            return self.shallow_clone
        if "--depth=1" in command:
            assert self.tip_probe is not None
            return self.tip_probe
        return ExecutionResult(stdout=f"\x01{_SHA_A}\x1f2026-07-10T10:00:00+00:00\npath.py\n", stderr="", exit_code=0)

    def destroy(self) -> None:
        self.destroyed = True


def _collect(sandbox: _FakeSandbox):
    github = MagicMock()
    github.get_access_token.return_value = _TOKEN
    sandbox_class = MagicMock()
    sandbox_class.create.return_value = sandbox
    module = "products.tasks.backend.logic.services.repo_commit_activity"
    with (
        patch(f"{module}.GitHubIntegration.first_for_team_repository", return_value=github),
        patch(f"{module}.get_sandbox_class", return_value=sandbox_class),
    ):
        return collect_repository_commit_activity(1, "acme/widgets")


def test_collect_reads_log_when_window_has_recent_commits():
    sandbox = _FakeSandbox(shallow_clone=_OK)

    commits = _collect(sandbox)

    assert [c.sha for c in commits] == [_SHA_A]
    assert not any("--depth=1" in command for command in sandbox.commands)
    assert sandbox.destroyed


def test_collect_returns_empty_when_latest_commit_predates_window():
    sandbox = _FakeSandbox(shallow_clone=_SHALLOW_INFO_FAILURE, tip_probe=_OK)

    assert _collect(sandbox) == []
    assert sandbox.destroyed


@parameterized.expand(
    [
        ("tip_inside_window", _SHALLOW_INFO_FAILURE, ExecutionResult(stdout=f"{_SHA_A}\n", stderr="", exit_code=0)),
        ("tip_probe_fails", _SHALLOW_INFO_FAILURE, ExecutionResult(stdout="", stderr="boom", exit_code=128)),
        ("unrelated_clone_failure", ExecutionResult(stdout="", stderr=f"denied {_TOKEN}", exit_code=128), None),
    ]
)
def test_collect_raises_when_history_is_unavailable(_name, shallow_clone, tip_probe):
    sandbox = _FakeSandbox(shallow_clone=shallow_clone, tip_probe=tip_probe)

    with pytest.raises(RepositoryCommitActivityError) as error:
        _collect(sandbox)

    assert _TOKEN not in str(error.value)
    assert sandbox.destroyed
