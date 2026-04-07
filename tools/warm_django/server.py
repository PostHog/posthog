"""
Django Warm Server — pre-fork daemon for instant manage.py and pytest startup.

Runs django.setup() once, then listens on a Unix socket. When a client
connects, the server forks itself. The child evicts any modules whose
source files changed since startup (by mtime), then runs the command.
This means you always get fresh code without needing to restart the daemon.

Usage:
    # Start the daemon (typically via phrocs/mprocs):
    python -m tools.warm_django.server

    # Run commands instantly via the client:
    bin/warm-django manage shell
    bin/warm-django pytest posthog/test/test_utils.py -x
"""

import os
import sys
import json
import time
import signal
import socket
import struct
import hashlib
import importlib

SOCKET_DIR = "/tmp"


def get_socket_path() -> str:
    """Deterministic socket path based on the repo root, matching phrocs convention."""
    repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    h = hashlib.sha256(repo_root.encode()).hexdigest()[:12]
    return os.path.join(SOCKET_DIR, f"warm-django-{h}.sock")


def _send_msg(conn: socket.socket, data: dict) -> None:
    """Send a length-prefixed JSON message."""
    payload = json.dumps(data).encode()
    conn.sendall(struct.pack("!I", len(payload)) + payload)


def _recv_msg(conn: socket.socket) -> dict | None:
    """Receive a length-prefixed JSON message."""
    header = b""
    while len(header) < 4:
        chunk = conn.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk
    (length,) = struct.unpack("!I", header)
    data = b""
    while len(data) < length:
        chunk = conn.recv(min(length - len(data), 65536))
        if not chunk:
            return None
        data += chunk
    return json.loads(data)


class _SocketWriter:
    """Redirect stdout/stderr over the socket to the client."""

    def __init__(self, conn: socket.socket, stream: str):
        self.conn = conn
        self.stream = stream

    def write(self, data: str) -> int:
        if data:
            try:
                _send_msg(self.conn, {"type": "output", "stream": self.stream, "data": data})
            except (BrokenPipeError, ConnectionResetError):
                pass
        return len(data)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        return self.conn.fileno()

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
        _send_msg(conn, {"type": "exit", "code": exit_code})
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

    print(  # noqa: T201
        f"warm-django: ready in {warm_time:.1f}s — tracking {len(mtimes)} modules",
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

        msg = _recv_msg(conn)
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
