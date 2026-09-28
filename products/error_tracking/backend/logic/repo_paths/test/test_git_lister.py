import os
import socket
import ipaddress
import threading
import subprocess
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.security.url_validation import PinnedUrlVerdict

from products.error_tracking.backend.logic.repo_paths import git_lister
from products.error_tracking.backend.logic.repo_paths.git_lister import (
    GitAuthFailed,
    GitCommitNotFound,
    GitFailed,
    GitFetchTarget,
    GitHostNotAllowed,
    GitListError,
    GitRemote,
    GitTimeout,
    GitTooLarge,
    can_read_repository,
    github_auth_header,
    list_repository_files,
)

TOKEN = "ghs_exampletoken0123456789"
FILES = ["README.md", "services/api/acme_api/orders/views.py", "apps/web/src/zażółć.ts", "a/b/c/d/e.txt"]
# DNS never resolves the .invalid TLD, so git reaches a test server under this name only through the pinned address.
PINNED_HOST = "git.example.invalid"


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
def local_remotes() -> Iterator[None]:
    loopback = PinnedUrlVerdict(allowed=True, reason=None, pinned_ips={ipaddress.IPv4Address("127.0.0.1")})
    with (
        patch.object(git_lister, "_ALLOWED_PROTOCOLS", frozenset({"file", "http"})),
        patch.object(git_lister, "validate_url_and_pin_ips", return_value=loopback),
    ):
        yield


@pytest.fixture
def served_repo(tmp_path: Path, local_remotes: None) -> tuple[str, str]:
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
def rejecting_server(local_remotes: None) -> Iterator[tuple[str, list[str]]]:
    received: list[str] = []
    handler = type("Handler", (_RecordingHandler,), {"received_auth": received})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{PINNED_HOST}:{server.server_address[1]}/acme/shop.git", received
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def silent_server(local_remotes: None) -> Iterator[str]:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        yield f"http://{PINNED_HOST}:{listener.getsockname()[1]}/acme/shop.git"


@pytest.fixture
def fake_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local_remotes: None) -> Callable[[str], None]:
    def install(stderr_command: str) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        script = bin_dir / "git"
        script.write_text(f"#!/bin/sh\n{{ {stderr_command}; }} >&2\nexit 128\n")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    return install


def _target(url: str, commit: str, *, max_bytes: int = 10_000_000, timeout: float = 30.0) -> GitFetchTarget:
    return GitFetchTarget(
        remote=GitRemote(url=url, auth_header=github_auth_header(TOKEN)),
        commit=commit,
        max_bytes=max_bytes,
        timeout_seconds=timeout,
    )


def _recorded_fetch_bytes(outcome: str) -> float:
    return REGISTRY.get_sample_value("error_tracking_repo_paths_git_fetch_bytes_sum", {"outcome": outcome}) or 0.0


def test_lists_every_path_sorted(served_repo: tuple[str, str]) -> None:
    url, commit = served_repo

    result = list_repository_files(_target(url, commit))

    assert result.commit == commit
    assert result.paths == tuple(sorted(FILES))
    assert result.fetched_bytes > 0


def test_missing_commit_raises_commit_not_found(served_repo: tuple[str, str]) -> None:
    url, _ = served_repo

    with pytest.raises(GitCommitNotFound):
        list_repository_files(_target(url, "1" * 40))


def test_fetch_above_the_byte_cap_raises_too_large_and_records_its_size(served_repo: tuple[str, str]) -> None:
    url, commit = served_repo
    recorded_before = _recorded_fetch_bytes("too_large")

    with pytest.raises(GitTooLarge):
        list_repository_files(_target(url, commit, max_bytes=1))

    assert _recorded_fetch_bytes("too_large") > recorded_before


def test_server_that_never_answers_raises_timeout(silent_server: str) -> None:
    with pytest.raises(GitTimeout):
        list_repository_files(_target(silent_server, "a" * 40, timeout=0.5))


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
            list_repository_files(_target(url, "a" * 40))

    expected_header = github_auth_header(TOKEN).removeprefix("Authorization: ")
    assert expected_header in received_auth
    assert spawned
    for args in spawned:
        assert not any(TOKEN in arg or expected_header in arg for arg in args)
    assert TOKEN not in str(raised.value)
    assert expected_header not in str(raised.value)


def test_token_cut_by_the_stderr_limit_is_still_redacted(fake_git: Callable[[str], None]) -> None:
    fake_git(f"printf '%s\\n' '{TOKEN}'; head -c {git_lister._STDERR_LIMIT - len(TOKEN) // 2} /dev/zero | tr '\\0' x")

    with pytest.raises(GitListError) as raised:
        list_repository_files(_target(f"http://{PINNED_HOST}/acme/shop.git", "a" * 40))

    assert TOKEN[-8:] not in str(raised.value)


def test_git_that_floods_stderr_is_stopped_before_the_timeout(fake_git: Callable[[str], None]) -> None:
    fake_git(f"head -c {2 * git_lister._STDERR_MAX_BYTES} /dev/zero; sleep 60")

    with pytest.raises(GitFailed):
        list_repository_files(_target(f"http://{PINNED_HOST}/acme/shop.git", "a" * 40, timeout=30))


def test_can_read_repository(served_repo: tuple[str, str], rejecting_server: tuple[str, list[str]]) -> None:
    served_url, _ = served_repo
    rejecting_url, _ = rejecting_server

    readable = GitRemote(url=served_url, auth_header=github_auth_header(TOKEN))
    rejected = GitRemote(url=rejecting_url, auth_header=github_auth_header(TOKEN))

    assert can_read_repository(readable, timeout_seconds=30) is True
    assert can_read_repository(rejected, timeout_seconds=30) is False


@parameterized.expand(
    [
        (
            "list",
            lambda remote: list_repository_files(
                GitFetchTarget(remote=remote, commit="a" * 40, max_bytes=10_000_000, timeout_seconds=30)
            ),
        ),
        ("probe", lambda remote: can_read_repository(remote, timeout_seconds=30)),
    ]
)
def test_internal_host_never_reaches_git(_name: str, call: Callable[[GitRemote], object]) -> None:
    remote = GitRemote(url="https://10.0.0.1/acme/shop.git", auth_header=github_auth_header(TOKEN))

    with patch.object(git_lister.subprocess, "Popen") as popen:
        with pytest.raises(GitHostNotAllowed):
            call(remote)

    popen.assert_not_called()


@parameterized.expand(
    [
        ("credentials_in_url", "https://x-access-token:secret@github.com/acme/shop.git"),
        ("plain_http", "http://github.com/acme/shop.git"),
        ("ssh_protocol", "ssh://git@github.com/acme/shop.git"),
        ("local_path", "file:///srv/git/shop.git"),
    ]
)
def test_remote_rejects_unsafe_urls(_name: str, url: str) -> None:
    with pytest.raises(ValueError):
        GitRemote(url=url, auth_header=github_auth_header(TOKEN))
