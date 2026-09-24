import os
import socket
import threading
import subprocess
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.error_tracking.backend.logic.repo_paths import git_lister
from products.error_tracking.backend.logic.repo_paths.git_lister import (
    GitAuthFailed,
    GitCommitNotFound,
    GitFetchTarget,
    GitRemote,
    GitTimeout,
    GitTooLarge,
    can_read_repository,
    github_auth_header,
    list_repository_files,
)

TOKEN = "ghs_exampletoken0123456789"
FILES = ["README.md", "services/api/acme_api/orders/views.py", "apps/web/src/zażółć.ts", "a/b/c/d/e.txt"]
LOCAL = frozenset({"file"})
HTTP = frozenset({"http"})


def _git(*args: str, cwd: Path) -> str:
    # The developer's own git config (commit signing, credential helpers) must not reach the fixture.
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(cwd),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "acme",
        "GIT_AUTHOR_EMAIL": "dev@example.com",
        "GIT_COMMITTER_NAME": "acme",
        "GIT_COMMITTER_EMAIL": "dev@example.com",
    }
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def served_repo(tmp_path: Path) -> tuple[str, str]:
    repo = tmp_path / "shop"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    for name in FILES:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(f"contents of {name}\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    _git("config", "uploadpack.allowFilter", "true", cwd=repo)
    _git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=repo)
    return f"file://{repo}", _git("rev-parse", "HEAD", cwd=repo)


class _RecordingHandler(BaseHTTPRequestHandler):
    received_auth: list[str] = []

    def do_GET(self) -> None:
        self.received_auth.append(self.headers.get("Authorization", ""))
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="acme"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def rejecting_server() -> Iterator[tuple[str, list[str]]]:
    received: list[str] = []
    handler = type("Handler", (_RecordingHandler,), {"received_auth": received})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/acme/shop.git", received
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def silent_server() -> Iterator[str]:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}/acme/shop.git"


def _target(url: str, commit: str, *, protocols: frozenset[str], max_bytes: int = 10_000_000, timeout: float = 30.0):
    return GitFetchTarget(
        remote=GitRemote(url=url, auth_header=github_auth_header(TOKEN), allowed_protocols=protocols),
        commit=commit,
        max_bytes=max_bytes,
        timeout_seconds=timeout,
    )


def test_lists_every_path_sorted(served_repo: tuple[str, str]) -> None:
    url, commit = served_repo

    result = list_repository_files(_target(url, commit, protocols=LOCAL))

    assert result.commit == commit
    assert result.paths == tuple(sorted(FILES))
    assert result.fetched_bytes > 0


def test_missing_commit_raises_commit_not_found(served_repo: tuple[str, str]) -> None:
    url, _ = served_repo

    with pytest.raises(GitCommitNotFound):
        list_repository_files(_target(url, "1" * 40, protocols=LOCAL))


def test_fetch_above_the_byte_cap_raises_too_large(served_repo: tuple[str, str]) -> None:
    url, commit = served_repo

    with pytest.raises(GitTooLarge):
        list_repository_files(_target(url, commit, protocols=LOCAL, max_bytes=1))


def test_server_that_never_answers_raises_timeout(silent_server: str) -> None:
    with pytest.raises(GitTimeout):
        list_repository_files(_target(silent_server, "a" * 40, protocols=HTTP, timeout=0.5))


def test_token_reaches_the_server_in_a_header_and_never_argv_or_errors(
    rejecting_server: tuple[str, list[str]],
) -> None:
    url, received_auth = rejecting_server
    spawned: list[list[str]] = []
    real_popen = subprocess.Popen

    def recording_popen(args: list[str], **kwargs: Any) -> object:
        spawned.append(args)
        return real_popen(args, **kwargs)

    with patch.object(git_lister.subprocess, "Popen", side_effect=recording_popen):
        with pytest.raises(GitAuthFailed) as raised:
            list_repository_files(_target(url, "a" * 40, protocols=HTTP))

    expected_header = github_auth_header(TOKEN).removeprefix("Authorization: ")
    assert expected_header in received_auth
    assert spawned
    for args in spawned:
        assert not any(TOKEN in arg or expected_header in arg for arg in args)
    assert TOKEN not in str(raised.value)
    assert expected_header not in str(raised.value)


def test_can_read_repository(served_repo: tuple[str, str], rejecting_server: tuple[str, list[str]]) -> None:
    served_url, _ = served_repo
    rejecting_url, _ = rejecting_server

    readable = GitRemote(url=served_url, auth_header=github_auth_header(TOKEN), allowed_protocols=LOCAL)
    rejected = GitRemote(url=rejecting_url, auth_header=github_auth_header(TOKEN), allowed_protocols=HTTP)

    assert can_read_repository(readable, timeout_seconds=30) is True
    assert can_read_repository(rejected, timeout_seconds=30) is False


@parameterized.expand(
    [
        ("credentials_in_url", "https://x-access-token:secret@github.com/acme/shop.git"),
        ("ssh_protocol", "ssh://git@github.com/acme/shop.git"),
        ("local_path", "file:///srv/git/shop.git"),
    ]
)
def test_remote_rejects_unsafe_urls(_name: str, url: str) -> None:
    with pytest.raises(ValueError):
        GitRemote(url=url, auth_header=github_auth_header(TOKEN))
