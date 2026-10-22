import os
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxConfig, parse_clone_phases

FAKE_DATE = """#!/bin/sh
if [ "$1" = "+%s%3N" ]; then
    echo "$(/bin/date +%s)000"
else
    exec /bin/date "$@"
fi
"""


def _git(cwd: Path, *args: str, env: dict[str, str]) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def git_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "date").write_text(FAKE_DATE)
    (bin_dir / "date").chmod(0o755)
    (tmp_path / "gitconfig").write_text(
        f'[url "file://{tmp_path}/remote/"]\n\tinsteadOf = https://github.com/\n'
        "[user]\n\tname = test\n\temail = test@example.com\n"
        "[init]\n\tdefaultBranch = master\n"
        "[protocol]\n\tallow = always\n"
    )
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }


@pytest.fixture
def remote(tmp_path: Path, git_env: dict[str, str]) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q", env=git_env)
    (source / "README.md").write_text("baked\n")
    _git(source, "add", "README.md", env=git_env)
    _git(source, "commit", "-q", "-m", "baked", env=git_env)
    bare = tmp_path / "remote" / "posthog" / "posthog.git"
    bare.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(source), str(bare), env=git_env)
    _git(source, "remote", "add", "origin", str(bare), env=git_env)
    return source


def _bake(tmp_path: Path, git_env: dict[str, str]) -> Path:
    baked = tmp_path / "repos" / "posthog" / "posthog"
    baked.parent.mkdir(parents=True)
    _git(
        tmp_path,
        "clone",
        "-q",
        "--depth",
        "1",
        f"file://{tmp_path}/remote/posthog/posthog.git",
        str(baked),
        env=git_env,
    )
    return baked


def _advance_remote(source: Path, git_env: dict[str, str], branch: str = "master") -> str:
    (source / "README.md").write_text("tip\n")
    _git(source, "commit", "-q", "-am", "tip", env=git_env)
    _git(source, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", env=git_env)
    return _git(source, "rev-parse", "HEAD", env=git_env)


def _clone(tmp_path: Path, git_env: dict[str, str], *, baked_repo_clone: bool) -> ExecutionResult:
    sandbox = ModalSandbox.__new__(ModalSandbox)
    sandbox.id = "sb-123"
    sandbox.config = SandboxConfig(name="test")
    sandbox._sandbox = MagicMock()

    def run(command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        completed = subprocess.run(["bash", "-c", command], env=git_env, capture_output=True, text=True)
        return ExecutionResult(stdout=completed.stdout, stderr=completed.stderr, exit_code=completed.returncode)

    with (
        patch("products.tasks.backend.logic.services.sandbox.SANDBOX_REPOSITORIES_ROOT", str(tmp_path / "repos")),
        patch.object(sandbox, "is_running", return_value=True),
        patch.object(sandbox, "execute", side_effect=run),
    ):
        return sandbox.clone_repository("PostHog/posthog", github_token="", baked_repo_clone=baked_repo_clone)


@pytest.mark.parametrize(
    "baked_repo_clone,break_head,expected_mode",
    [
        (True, False, "baked"),
        (False, False, "fresh"),
        (True, True, "fallback"),
    ],
)
def test_clone_repository_mode(tmp_path, git_env, remote, baked_repo_clone, break_head, expected_mode):
    baked = _bake(tmp_path, git_env)
    if break_head:
        hook = baked / ".git" / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\ngit commit -q --allow-empty -m drift\n")
        hook.chmod(0o755)
    _advance_remote(remote, git_env)

    result = _clone(tmp_path, git_env, baked_repo_clone=baked_repo_clone)

    phases = parse_clone_phases(result.stdout)
    assert phases is not None and phases.mode == expected_mode, result.stderr


@pytest.mark.parametrize("baked_repo_clone", [True, False])
def test_clone_repository_lands_on_the_remote_tip(tmp_path, git_env, remote, baked_repo_clone):
    _bake(tmp_path, git_env)
    tip = _advance_remote(remote, git_env)

    _clone(tmp_path, git_env, baked_repo_clone=baked_repo_clone)

    assert _git(tmp_path / "repos" / "posthog" / "posthog", "rev-parse", "HEAD", env=git_env) == tip


def test_baked_clone_follows_a_default_branch_changed_after_the_bake(tmp_path, git_env, remote):
    _bake(tmp_path, git_env)
    _advance_remote(remote, git_env, branch="trunk")
    _git(tmp_path / "remote" / "posthog" / "posthog.git", "symbolic-ref", "HEAD", "refs/heads/trunk", env=git_env)

    _clone(tmp_path, git_env, baked_repo_clone=True)

    assert _git(tmp_path / "repos" / "posthog" / "posthog", "branch", "--show-current", env=git_env) == "trunk"
