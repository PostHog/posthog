"""
Django Warm Server — pre-fork daemon for instant manage.py and pytest startup.

Runs django.setup() once, then listens on a Unix socket. When a client
connects, the server forks itself. The child evicts any modules whose
source files changed since startup (by mtime), then runs the command.
This means you always get fresh code without needing to restart the daemon.

Caveats:
    - Pytest's assertion rewriter cannot rewrite already-imported modules, so
      assertion error introspection is less rich for daemon-cached test
      dependencies (PytestAssertRewriteWarning is silenced for that reason).
      Test files imported fresh by pytest still get full rewriting.
    - Concurrent connections fork serially. For pytest-xdist with many
      workers, fork startup cost is paid per worker but the parent's
      single-threaded accept loop still serializes the kickoff.
    - Module-level mtime invalidation evicts stale code, but it cannot redo
      django.setup(). For changes that affect Django bootstrap (settings,
      .env, lockfile), the daemon detects the change at the next request and
      re-execs itself. The in-flight client falls back to cold start so the
      user gets a working command immediately.

Usage:
    # Start the daemon (typically via phrocs/mprocs):
    python -m tools.warm_django.server

    # Run commands instantly via the client:
    bin/warm-django manage shell
    bin/warm-django pytest posthog/test/test_utils.py -x
"""

import io
import os
import sys
import time
import signal
import socket
import importlib
import threading

from tools.warm_django._socket import get_socket_path, recv_msg, send_msg


class _SocketWriter:
    """Redirect stdout/stderr over the socket to the client."""

    def __init__(self, conn: socket.socket, stream: str):
        self.conn = conn
        self.stream = stream

    def write(self, data: str) -> int:
        if data:
            try:
                send_msg(self.conn, {"type": "output", "stream": self.stream, "data": data})
            except (BrokenPipeError, ConnectionResetError):
                pass
        return len(data)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        # Refusing fileno() forces pytest off its default fd-level capture
        # (which would dup2 the capture buffer over the raw socket fd and
        # silently swallow all output). With UnsupportedOperation, pytest
        # falls back to sys-level capture, which routes through write().
        raise io.UnsupportedOperation("fileno")

    @property
    def encoding(self) -> str:
        return "utf-8"

    def isatty(self) -> bool:
        return False


def _snapshot_mtimes(repo_root: str) -> dict[str, float]:
    """Record mtime for every loaded module with a .py file under repo_root."""
    mtimes = {}
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and f.startswith(repo_root) and f.endswith(".py"):
            try:
                mtimes[name] = os.stat(f).st_mtime
            except OSError:
                pass
    return mtimes


# Files/dirs whose change requires a fresh django.setup() — module reload
# alone is not enough because Django's app registry, settings cache, and
# DB/cache pools are global state set up once at boot.
_CONFIG_PATHS: tuple[str, ...] = (
    "posthog/settings",
    ".env",
    ".env.local",
    "pyproject.toml",
    "uv.lock",
)


class _ConfigWatcher:
    """Background filesystem watcher that flags the daemon for restart on config changes.

    Uses watchdog's native FS events (FSEvents on macOS, inotify on Linux) so
    detection is push-driven and effectively instantaneous — no per-request
    stat cost. The accept loop checks ``dirty.is_set()`` before each fork.
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root
        self.dirty = threading.Event()
        self.changed_path: str | None = None
        self._observer = None
        self._watch_count = 0

    def start(self) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        watcher_self = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:
                if event.is_directory:
                    return
                try:
                    rel = os.path.relpath(event.src_path, watcher_self.repo_root)
                except ValueError:
                    return
                if not any(rel == p or rel.startswith(p + os.sep) for p in _CONFIG_PATHS):
                    return
                watcher_self.changed_path = rel
                watcher_self.dirty.set()

        observer = Observer()
        observer.daemon = True
        watched_dirs: set[str] = set()
        for rel in _CONFIG_PATHS:
            path = os.path.join(self.repo_root, rel)
            if os.path.isdir(path):
                observer.schedule(_Handler(), path, recursive=True)
                watched_dirs.add(path)
                self._watch_count += 1
            elif os.path.exists(path):
                # Single file: watch its parent dir non-recursively; the handler filters by path.
                parent = os.path.dirname(path) or "."
                if parent not in watched_dirs:
                    observer.schedule(_Handler(), parent, recursive=False)
                    watched_dirs.add(parent)
                    self._watch_count += 1
        observer.start()
        self._observer = observer

    @property
    def watch_count(self) -> int:
        return self._watch_count


def _evict_stale_modules(mtimes: dict[str, float]) -> list[str]:
    """Remove modules from sys.modules whose source changed since startup.

    Returns list of evicted module names. Next import of these modules
    will read the fresh .py file from disk.
    """
    evicted = []
    for name, old_mtime in mtimes.items():
        mod = sys.modules.get(name)
        if mod is None:
            continue
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        try:
            if os.stat(f).st_mtime > old_mtime:
                evicted.append(name)
        except OSError:
            continue

    # Evict in reverse order (children before parents) to avoid partial state
    evicted.sort(key=lambda n: n.count("."), reverse=True)
    for name in evicted:
        sys.modules.pop(name, None)

    # Clear import caches so fresh imports pick up new files
    if evicted:
        importlib.invalidate_caches()

    return evicted


def _run_in_child(
    conn: socket.socket,
    mode: str,
    argv: list[str],
    env_overrides: dict,
    mtimes: dict[str, float],
) -> None:
    """Called in the forked child. Evicts stale modules, then runs the command."""
    for k, v in env_overrides.items():
        os.environ[k] = v

    sys.stdout = _SocketWriter(conn, "stdout")  # type: ignore[assignment]
    sys.stderr = _SocketWriter(conn, "stderr")  # type: ignore[assignment]

    # Evict modules whose source changed since daemon startup
    evicted = _evict_stale_modules(mtimes)
    if evicted:
        sys.stderr.write(f"warm-django: reloaded {len(evicted)} changed module(s)\n")

    exit_code = 0
    try:
        if mode == "pytest":
            import warnings

            import pytest

            # Suppress PytestAssertRewriteWarning — modules pre-loaded by the daemon
            # can't be rewritten, but this is harmless (only affects assert error messages)
            warnings.filterwarnings("ignore", category=pytest.PytestAssertRewriteWarning)

            sys.argv = ["pytest", *argv]
            exit_code = pytest.main(argv)
        elif mode == "manage":
            from django.core.management import execute_from_command_line

            sys.argv = ["manage.py", *argv]
            execute_from_command_line(sys.argv)
        else:
            sys.stderr.write(f"warm-django: unknown mode '{mode}'\n")
            exit_code = 1
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        exit_code = 1

    try:
        send_msg(conn, {"type": "exit", "code": exit_code})
    except (BrokenPipeError, ConnectionResetError):
        pass

    conn.close()
    os._exit(exit_code)


def serve() -> None:
    # Suppress the multi-threaded fork warning — Django creates threads during setup
    # (DB connections, cache clients) but forked children work fine for short-lived commands
    import warnings

    warnings.filterwarnings("ignore", message=".*multi-threaded.*use of fork.*", category=DeprecationWarning)

    socket_path = get_socket_path()
    repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))

    if os.path.exists(socket_path):
        os.unlink(socket_path)

    # Phase 1: Warm up Django
    t0 = time.perf_counter()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    # Always start in test mode — TEST=1 enables test utilities (bulk_create_persons etc.)
    # that pytest needs, and manage.py commands work fine with it set
    os.environ.setdefault("TEST", "1")
    os.environ.setdefault("DEBUG", "1")

    import django

    django.setup()

    # Phase 2: Pre-import pytest so it's cached in the fork
    import pytest  # noqa: F401

    warm_time = time.perf_counter() - t0

    # Phase 3: Snapshot mtimes of all loaded modules
    mtimes = _snapshot_mtimes(repo_root)

    # Phase 4: Start a real filesystem watcher for config-affecting files
    config_watcher = _ConfigWatcher(repo_root)
    config_watcher.start()

    print(  # noqa: T201
        f"warm-django: ready in {warm_time:.1f}s — tracking {len(mtimes)} modules, "
        f"watching {config_watcher.watch_count} config dir(s)",
        flush=True,
    )

    # Reap zombie children
    def _reap(signum, frame):
        while True:
            try:
                os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break

    signal.signal(signal.SIGCHLD, _reap)

    # Listen
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socket_path)
    os.chmod(socket_path, 0o600)
    sock.listen(5)

    def shutdown(signum, frame):
        print("\nwarm-django: shutting down", flush=True)  # noqa: T201
        sock.close()
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            break

        # Settings or env changed since warm-up — re-exec instead of forking
        # with stale Django state. Tells the in-flight client to fall back to
        # cold start so it gets a working command immediately.
        if config_watcher.dirty.is_set():
            changed = config_watcher.changed_path or "<unknown>"
            try:
                send_msg(conn, {"type": "fallback", "reason": f"config changed: {changed}"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            conn.close()
            print(f"warm-django: config changed ({changed}) — re-execing daemon", flush=True)  # noqa: T201
            sock.close()
            if os.path.exists(socket_path):
                os.unlink(socket_path)
            os.execv(sys.executable, [sys.executable, "-m", "tools.warm_django.server"])
            return  # unreachable

        msg = recv_msg(conn)
        if not msg or msg.get("type") != "run":
            conn.close()
            continue

        mode = msg.get("mode", "manage")
        argv = msg.get("argv", [])
        env_overrides = msg.get("env", {})

        t_fork = time.perf_counter()
        pid = os.fork()

        if pid == 0:
            sock.close()
            _run_in_child(conn, mode, argv, env_overrides, mtimes)
        else:
            conn.close()
            fork_ms = (time.perf_counter() - t_fork) * 1000
            cmd_preview = " ".join(argv[:4])
            if len(argv) > 4:
                cmd_preview += " ..."
            print(f"warm-django: forked {pid} for {mode} {cmd_preview} ({fork_ms:.0f}ms)", flush=True)  # noqa: T201


if __name__ == "__main__":
    serve()
