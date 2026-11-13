"""`hogli watch`: one background process for dev-environment housekeeping.

Flox activation and the pytest harness start it. A lock file keeps one copy per machine. It runs
the daily worktree cleanup, and it stops the local ClickHouse after a stretch with no use. It exits
when no job has anything left to watch, so it is not a permanent daemon.
"""

from __future__ import annotations

import os
import sys
import time
import fcntl
import subprocess
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import click

from .doctor import _STOP_GRACE_SECONDS, _compose_project_name
from .worktrees import _UNATTENDED_LOCK

LOCK_PATH = Path.home() / ".config" / "posthog" / "watch.lock"
LOG_PATH = Path.home() / ".cache" / "posthog" / "watch.log"
TICK_SECONDS = 60
CLICKHOUSE_HTTP_URL = "http://localhost:8123"
DEFAULT_CLICKHOUSE_IDLE_MINUTES = 30
CLICKHOUSE_READY_TIMEOUT_SECONDS = 60
# Compose would start these with ClickHouse, because clickhouse depends_on them.
CLICKHOUSE_SERVICES = ("zookeeper", "kafka", "clickhouse")


def _log(message: str) -> None:
    # UTC, because the pytest harness starts watchers from a process that Django switched to UTC.
    click.echo(f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} {message}")


def _run(cmd: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def watch_enabled() -> bool:
    return os.environ.get("POSTHOG_WATCH", "1") != "0" and not os.environ.get("CI")


def clickhouse_idle_minutes() -> int:
    """Minutes without use before the watcher stops ClickHouse. 0 turns the stop off."""
    raw = os.environ.get("POSTHOG_CLICKHOUSE_IDLE_STOP_MINUTES", str(DEFAULT_CLICKHOUSE_IDLE_MINUTES))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CLICKHOUSE_IDLE_MINUTES


class ComposeService:
    """One service of the shared dev compose project, found by its compose labels."""

    def __init__(self, service: str) -> None:
        self.service = service
        self.project = _compose_project_name()

    def _container(self) -> tuple[str, str] | None:
        result = _run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
                "--filter",
                f"label=com.docker.compose.service={self.service}",
                "--format",
                "{{.ID}} {{.State}}",
            ],
            timeout=10,
        )
        if result is None or result.returncode != 0 or not result.stdout.strip():
            return None
        container_id, state = result.stdout.strip().splitlines()[0].split(" ", 1)
        return container_id, state

    def exists(self) -> bool:
        return self._container() is not None

    def is_running(self) -> bool:
        container = self._container()
        return container is not None and container[1] == "running"

    def start(self) -> bool:
        container = self._container()
        if container is None:
            return False
        if container[1] == "running":
            return True
        result = _run(["docker", "start", container[0]], timeout=60)
        return result is not None and result.returncode == 0

    def stop(self) -> bool:
        container = self._container()
        if container is None or container[1] != "running":
            return True
        result = _run(
            ["docker", "stop", "-t", str(_STOP_GRACE_SECONDS), container[0]], timeout=_STOP_GRACE_SECONDS + 30
        )
        return result is not None and result.returncode == 0


@dataclass(frozen=True, kw_only=True, slots=True)
class ClickHouseUsage:
    """What one tick saw. `query_count` is ClickHouse's running total, which resets on restart."""

    query_count: int
    client_connections: int
    stack_running: bool


def _clickhouse_query(sql: str) -> str | None:
    request = urllib.request.Request(CLICKHOUSE_HTTP_URL, data=sql.encode(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body: bytes = response.read()
    except (urllib.error.URLError, OSError):
        return None
    return body.decode().strip()


# The process runners of `hogli start` (also detached), and the web server and Celery when run by hand.
STACK_PROCESS_PATTERNS = (["-x", "phrocs"], ["-x", "mprocs"], ["-f", "granian"], ["-f", "run_autoreload_celery"])


def _stack_running() -> bool:
    """True while the dev app or its workers run. They need ClickHouse even when nobody uses them."""
    for pattern in STACK_PROCESS_PATTERNS:
        result = _run(["pgrep", *pattern], timeout=5)
        if result is not None and result.returncode == 0:
            return True
    return False


def read_clickhouse_usage() -> ClickHouseUsage | None:
    # This HTTP request is itself one query and one HTTP connection, so the idle check subtracts it.
    raw = _clickhouse_query(
        "SELECT (SELECT value FROM system.events WHERE event = 'Query'),"
        " (SELECT sum(value) FROM system.metrics WHERE metric IN ('TCPConnection', 'HTTPConnection'))"
        " FORMAT TSV"
    )
    if raw is None:
        return None
    try:
        query_count, connections = (int(value) for value in raw.split("\t"))
    except ValueError:
        return None
    return ClickHouseUsage(
        query_count=query_count, client_connections=max(0, connections - 1), stack_running=_stack_running()
    )


class ClickHouseIdleStop:
    """Stops the local ClickHouse after `idle_minutes` with no queries, no clients and no dev stack."""

    def __init__(self, idle_minutes: int, now: float) -> None:
        self.idle_seconds = idle_minutes * 60
        self.last_active = now
        self.last_query_count: int | None = None

    def observe(self, usage: ClickHouseUsage, now: float) -> bool:
        """Record one tick and return True when ClickHouse has been idle for the whole window."""
        new_queries = self.last_query_count is None or usage.query_count - self.last_query_count != 1
        self.last_query_count = usage.query_count
        if usage.stack_running or usage.client_connections > 0 or new_queries:
            self.last_active = now
            return False
        return now - self.last_active >= self.idle_seconds


class WorktreeCleanup:
    """Runs `worktrees:clean --unattended` once a day. That command keeps its own lock and log."""

    def __init__(self) -> None:
        self.last_attempt: float | None = None

    def is_due(self) -> bool:
        if os.environ.get("POSTHOG_WORKTREES_AUTOCLEAN", "1") == "0":
            return False
        # A run that fails before it writes its lock would otherwise look due on every tick.
        if self.last_attempt is not None and time.time() - self.last_attempt < 24 * 60 * 60:
            return False
        try:
            last_run = _UNATTENDED_LOCK.stat()
        except FileNotFoundError:
            return True
        return last_run.st_size == 0 or time.time() - last_run.st_mtime >= 24 * 60 * 60

    def run(self) -> None:
        self.last_attempt = time.time()
        _log("running worktrees:clean --unattended")
        # Its output goes to the watcher's stdout, which is the watch log.
        try:
            subprocess.run(
                [sys.executable, "-P", "-m", "hogli", "worktrees:clean", "--unattended"], timeout=60 * 60, check=False
            )
        except (OSError, subprocess.SubprocessError) as error:
            _log(f"worktrees:clean failed: {error}")


def _take_lock() -> IO[str] | None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    lock.seek(0)
    lock.truncate(0)
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def _watcher_pid() -> int | None:
    """The pid of the running watcher, or None when no watcher holds the lock."""
    if not LOCK_PATH.exists():
        return None
    with LOCK_PATH.open("r") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            content = lock.read().strip()
            return int(content) if content.isdigit() else -1
        fcntl.flock(lock, fcntl.LOCK_UN)
    return None


def spawn_watcher() -> None:
    """Start a detached watcher. It exits at once when another one already holds the lock."""
    if not watch_enabled():
        return
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as log:
        subprocess.Popen(
            [sys.executable, "-P", "-m", "hogli", "watch"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def run_watcher() -> None:
    lock = _take_lock()
    if lock is None:
        return
    cleanup = WorktreeCleanup()
    clickhouse = ComposeService("clickhouse")
    idle_minutes = clickhouse_idle_minutes()
    idle_stop = ClickHouseIdleStop(idle_minutes, now=time.monotonic())
    _log(f"watcher started (pid {os.getpid()}, ClickHouse idle stop after {idle_minutes} min)")
    try:
        while True:
            if cleanup.is_due():
                cleanup.run()
            if idle_minutes == 0 or not clickhouse.is_running():
                _log("nothing left to watch, exiting")
                return
            usage = read_clickhouse_usage()
            if usage is not None and idle_stop.observe(usage, now=time.monotonic()):
                _log(f"ClickHouse unused for {idle_minutes} min, stopping it")
                clickhouse.stop()
                _log("nothing left to watch, exiting")
                return
            time.sleep(TICK_SECONDS)
    finally:
        lock.truncate(0)
        lock.close()


def ensure_clickhouse() -> bool:
    """Start the local ClickHouse if it is stopped, wait until it answers, and arm the watcher."""
    services = [ComposeService(name) for name in CLICKHOUSE_SERVICES]
    if not services[-1].exists():
        click.echo("No local ClickHouse container exists. Run `hogli start` once to create the dev stack.", err=True)
        return False
    if not services[-1].is_running():
        click.echo("Starting the local ClickHouse container...", err=True)
        for service in services:
            service.start()
    deadline = time.monotonic() + CLICKHOUSE_READY_TIMEOUT_SECONDS
    while _clickhouse_query("SELECT 1") != "1":
        if time.monotonic() > deadline:
            click.echo(
                "ClickHouse did not answer within 60 s. Check `docker compose -f docker-compose.dev.yml logs clickhouse`.",
                err=True,
            )
            return False
        time.sleep(0.5)
    spawn_watcher()
    return True


def _print_status() -> None:
    pid = _watcher_pid()
    click.echo(f"Watcher: {'running (pid ' + str(pid) + ')' if pid else 'not running'}")
    clickhouse = ComposeService("clickhouse")
    state = "running" if clickhouse.is_running() else ("stopped" if clickhouse.exists() else "no container")
    click.echo(f"ClickHouse: {state}")
    minutes = clickhouse_idle_minutes()
    click.echo(f"ClickHouse idle stop: {f'after {minutes} min' if minutes else 'off'}")
    cleanup = WorktreeCleanup()
    click.echo(f"Worktree cleanup: {'due' if cleanup.is_due() else 'ran in the last 24 h or turned off'}")
    if not watch_enabled():
        click.echo("POSTHOG_WATCH=0 or CI is set, so nothing starts the watcher.")
    click.echo(f"Log: {LOG_PATH}")


@click.command(name="watch")
@click.option(
    "--ensure",
    type=click.Choice(["clickhouse"]),
    help="Start the service if it is stopped, wait until it answers, and arm the watcher.",
)
@click.option("--status", is_flag=True, help="Show the watcher, its jobs and the ClickHouse state.")
def watch(ensure: str | None, status: bool) -> None:
    """Run dev-environment housekeeping: daily worktree cleanup and the ClickHouse idle stop."""
    if status:
        _print_status()
        return
    if ensure == "clickhouse":
        raise SystemExit(0 if ensure_clickhouse() else 1)
    run_watcher()
