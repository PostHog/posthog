"""Shared git scaffolding for the tests that exercise real repository history."""

import os
import subprocess
from pathlib import Path

import pytest

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
    )


def write(repo: Path, path: str, content: str = "x") -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def commit(repo: Path, message: str) -> str:
    git("add", "-A", cwd=repo)
    git("commit", "-m", message, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def head(repo: Path) -> str:
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Empty repo with one initial commit on master."""
    git("init", "--initial-branch=master", cwd=tmp_path)
    write(tmp_path, "README.md", "init")
    commit(tmp_path, "init")
    return tmp_path
