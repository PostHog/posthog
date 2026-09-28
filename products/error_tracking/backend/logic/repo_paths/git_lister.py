"""List the files of one repository commit with git, without downloading file contents.

The fetch is shallow (one commit) and blobless (trees only), so it reads the paths of a large
repository in seconds. Git runs with a customer's token, so every setting that could leak the
token or run customer-controlled code is fixed here, and callers cannot change it.
"""

import os
import re
import time
import base64
import shutil
import signal
import tempfile
import ipaddress
import subprocess
from dataclasses import field
from pathlib import Path
from typing import IO, Literal
from urllib.parse import urlsplit

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import select_pinned_ip
from posthog.security.url_validation import validate_url_and_pin_ips

from products.error_tracking.backend.logic.repo_paths.metrics import record_git_fetch

GitFetchOutcome = Literal[
    "listed", "auth_failed", "commit_not_found", "too_large", "timeout", "host_not_allowed", "error"
]

_ALLOWED_PROTOCOLS: frozenset[str] = frozenset({"https"})
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_POLL_SECONDS = 0.2
_STDERR_LIMIT = 2000
_STDERR_MAX_BYTES = 1024 * 1024
# The tail is redacted before it is cut to _STDERR_LIMIT characters. The window is far longer than
# the kept text, so a secret that the window start cuts in two falls outside the kept text.
_STDERR_TAIL_BYTES = 64 * 1024
_REDACTED = "[REDACTED]"

# Environment variables that only select a network route or a CA bundle. The worker may need them
# to reach the git host, and none of them can run a program.
_PASSTHROUGH_ENV = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


class GitListError(Exception):
    outcome: GitFetchOutcome = "error"


class GitAuthFailed(GitListError):
    outcome = "auth_failed"


class GitCommitNotFound(GitListError):
    outcome = "commit_not_found"


class GitTooLarge(GitListError):
    outcome = "too_large"


class GitTimeout(GitListError):
    outcome = "timeout"


class GitHostNotAllowed(GitListError):
    outcome = "host_not_allowed"


class GitFailed(GitListError):
    outcome = "error"


@frozen
class GitRemote:
    url: str
    auth_header: str = field(repr=False)

    def __post_init__(self) -> None:
        parts = urlsplit(self.url)
        if parts.scheme not in _ALLOWED_PROTOCOLS:
            raise ValueError(f"Protocol {parts.scheme!r} is not allowed")
        if parts.username or parts.password:
            raise ValueError("The URL must not contain credentials")
        if not self.auth_header or "\n" in self.auth_header or "\r" in self.auth_header:
            raise ValueError("The auth header must be one non-empty line")

    def secrets(self) -> tuple[str, ...]:
        """Every form of the credential that git could echo, longest first."""
        _, _, value = self.auth_header.partition(":")
        value = value.strip()
        _, _, encoded = value.partition(" ")
        fragments = [self.auth_header, value, encoded]
        try:
            _, _, token = base64.b64decode(encoded, validate=True).decode().partition(":")
            fragments.append(token)
        except ValueError:
            pass
        return tuple(sorted({f for f in fragments if len(f) >= 8}, key=len, reverse=True))


@frozen
class GitFetchTarget:
    remote: GitRemote
    commit: str
    max_bytes: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        if not _COMMIT_RE.match(self.commit):
            raise ValueError("The commit must be a 40-character lowercase hex SHA")
        if self.max_bytes <= 0 or self.timeout_seconds <= 0:
            raise ValueError("The byte cap and the timeout must be positive")


@frozen
class RepoFileList:
    commit: str
    paths: tuple[str, ...]
    fetched_bytes: int
    seconds: float


def github_auth_header(token: str) -> str:
    return _basic_auth_header("x-access-token", token)


def gitlab_auth_header(token: str) -> str:
    # GitLab accepts any non-empty user name with a project access token as the password.
    return _basic_auth_header("oauth2", token)


def _basic_auth_header(user: str, token: str) -> str:
    encoded = base64.b64encode(f"{user}:{token}".encode()).decode()
    return f"Authorization: Basic {encoded}"


def list_repository_files(target: GitFetchTarget) -> RepoFileList:
    """Return every file path of ``target.commit``, sorted.

    Raises a ``GitListError`` subclass on failure. Paths that are not valid UTF-8 or that contain a
    newline are dropped, because the stored list is newline-separated UTF-8 text.
    """
    started = time.monotonic()
    deadline = started + target.timeout_seconds
    outcome: GitFetchOutcome = "error"
    run: _GitRunner | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="error-tracking-repo-paths-") as tmp:
            workdir = Path(tmp)
            repo = workdir / "repo.git"
            env = _git_env(target.remote, home=workdir)
            run = _GitRunner(remote=target.remote, env=env, cwd=workdir, deadline=deadline)

            run(["git", "init", "--bare", "-q", "--template=", str(repo)])
            run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "fetch",
                    "--depth=1",
                    "--filter=blob:none",
                    "--no-tags",
                    "-q",
                    target.remote.url,
                    target.commit,
                ],
                watch_dir=repo / "objects",
                max_bytes=target.max_bytes,
            )
            listing = run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z", target.commit])
        paths = tuple(sorted(_decode_paths(listing)))
        outcome = "listed"
        return RepoFileList(
            commit=target.commit,
            paths=paths,
            fetched_bytes=run.watched_bytes,
            seconds=time.monotonic() - started,
        )
    except GitListError as e:
        outcome = e.outcome
        raise
    finally:
        fetched_bytes = run.watched_bytes if run is not None else 0
        record_git_fetch(outcome=outcome, seconds=time.monotonic() - started, fetched_bytes=fetched_bytes)


def can_read_repository(remote: GitRemote, *, timeout_seconds: float) -> bool:
    """Whether the credential can read the repository. Other failures raise ``GitListError``."""
    with tempfile.TemporaryDirectory(prefix="error-tracking-repo-probe-") as tmp:
        workdir = Path(tmp)
        run = _GitRunner(
            remote=remote,
            env=_git_env(remote, home=workdir),
            cwd=workdir,
            deadline=time.monotonic() + timeout_seconds,
        )
        try:
            run(["git", "ls-remote", remote.url, "HEAD"])
        except GitAuthFailed:
            return False
    return True


def _git_env(remote: GitRemote, *, home: Path) -> dict[str, str]:
    # Config goes through the environment and never through argv, so the credential does not show
    # in the process list. The environment starts empty, so no inherited GIT_* variable (a trace
    # file, an SSH command, a config path) reaches git.
    config: list[tuple[str, str]] = [
        ("http.extraHeader", remote.auth_header),
        ("http.followRedirects", "false"),
        ("protocol.version", "2"),
        ("protocol.allow", "never"),
        *((f"protocol.{protocol}.allow", "always") for protocol in sorted(_ALLOWED_PROTOCOLS)),
        ("core.hooksPath", os.devnull),
        ("credential.helper", ""),
        *(("http.curloptResolve", entry) for entry in _pinned_host_entries(remote.url)),
    ]
    env = {name: os.environ[name] for name in _PASSTHROUGH_ENV if name in os.environ}
    env.update(
        {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": shutil.which("true") or "/bin/true",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            # A blobless clone fetches a missing object on demand. Listing needs only trees, so any
            # such fetch is a bug, and it must fail instead of going to the network.
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_CONFIG_COUNT": str(len(config)),
        }
    )
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def _pinned_host_entries(url: str) -> list[str]:
    """Check the host of ``url`` and return the libcurl resolve entry that pins git to the checked IP.

    Git resolves the host again when it connects. Without the pin, a DNS record that changes
    between the check and the connection could send git and the token to an internal address.
    """
    verdict = validate_url_and_pin_ips(url)
    if not verdict.allowed:
        raise GitHostNotAllowed(verdict.reason or "The git host is not allowed")
    ip = select_pinned_ip(verdict.pinned_ips)
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ip is None or not host or _is_ip_literal(host):
        return []
    # libcurl looks up resolve entries by the host it connects to. For a non-ASCII host that is the
    # IDNA form, so an entry under the raw host would not match and git would use DNS instead.
    if not host.isascii():
        raise GitHostNotAllowed("The git host must be an ASCII hostname")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    address = f"[{ip}]" if ip.version == 6 else str(ip)
    return [f"{host}:{port}:{address}"]


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class _GitRunner:
    def __init__(self, *, remote: GitRemote, env: dict[str, str], cwd: Path, deadline: float) -> None:
        self._remote = remote
        self._env = env
        self._cwd = cwd
        self._deadline = deadline
        self.watched_bytes = 0

    def __call__(self, args: list[str], *, watch_dir: Path | None = None, max_bytes: int = 0) -> bytes:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            # A new session makes git and its transport helper one process group, so a kill stops both.
            process = subprocess.Popen(
                args,
                cwd=self._cwd,
                env=self._env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                self._wait(process, stderr, watch_dir, max_bytes)
            finally:
                if process.poll() is None:
                    _kill(process)
                if watch_dir is not None:
                    self.watched_bytes = _dir_size(watch_dir)
            # A fast fetch can finish between two checks, so check the size once more at the end.
            # This also catches a server that ignores the blob filter and sends every file.
            if watch_dir is not None and self.watched_bytes > max_bytes:
                raise GitTooLarge(f"The fetch passed the cap of {max_bytes} bytes")
            if process.returncode != 0:
                raise _classify(self._redacted_tail(stderr))
            stdout.seek(0)
            return stdout.read()

    def _wait(
        self, process: subprocess.Popen[bytes], stderr: IO[bytes], watch_dir: Path | None, max_bytes: int
    ) -> None:
        while True:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise GitTimeout("git did not finish before the timeout")
            try:
                process.wait(timeout=min(_POLL_SECONDS, remaining))
                return
            except subprocess.TimeoutExpired:
                pass
            if os.fstat(stderr.fileno()).st_size > _STDERR_MAX_BYTES:
                raise GitFailed(f"git wrote more than {_STDERR_MAX_BYTES} bytes to stderr")
            if watch_dir is not None and _dir_size(watch_dir) > max_bytes:
                raise GitTooLarge(f"The fetch passed the cap of {max_bytes} bytes")

    def _redacted_tail(self, stderr: IO[bytes]) -> str:
        text = _read_tail(stderr)
        for secret in self._remote.secrets():
            text = text.replace(secret, _REDACTED)
        return text[-_STDERR_LIMIT:].strip()


def _kill(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _read_tail(file: IO[bytes]) -> str:
    file.seek(max(0, os.fstat(file.fileno()).st_size - _STDERR_TAIL_BYTES))
    return file.read(_STDERR_TAIL_BYTES).decode("utf-8", errors="replace")


_AUTH_FAILURES = (
    "authentication failed",
    "could not read username",
    "could not read password",
    "returned error: 401",
    "returned error: 403",
    # GitHub and GitLab answer 404 for a private repository that the token cannot see.
    "repository not found",
)
_REPOSITORY_NOT_FOUND_RE = re.compile(r"repository '[^']*' not found")
_MISSING_COMMIT = (
    "not our ref",
    "unadvertised object",
    "couldn't find remote ref",
    "no such remote ref",
)


def _classify(stderr: str) -> GitListError:
    lowered = stderr.lower()
    if any(marker in lowered for marker in _MISSING_COMMIT):
        return GitCommitNotFound(stderr)
    if any(marker in lowered for marker in _AUTH_FAILURES) or _REPOSITORY_NOT_FOUND_RE.search(lowered):
        return GitAuthFailed(stderr)
    return GitFailed(stderr)


def _decode_paths(listing: bytes) -> list[str]:
    paths: list[str] = []
    for raw in listing.split(b"\0"):
        if not raw or b"\n" in raw:
            continue
        try:
            paths.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return paths


def _dir_size(root: Path) -> int:
    total = 0
    pending = [root]
    while pending:
        # git renames and deletes temporary pack files while it runs, so entries can vanish mid-walk.
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            continue
    return total
