"""
Django Warm Client — connects to the pre-fork daemon and runs commands instantly.

Usage:
    python -m tools.warm_django.client manage shell
    python -m tools.warm_django.client pytest posthog/test/test_utils.py -x
    python -m tools.warm_django.client manage migrate

Falls back to running the command directly (cold start) if the daemon isn't running.
"""

import os
import sys
import json
import time
import socket
import struct

from tools.warm_django._socket import get_socket_path

# Env vars to forward to the daemon. Whitelisted prefixes only — the daemon's
# Django setup is a long-running process with its own env, and forwarding
# everything would leak shell-local junk. If you rely on a different env var
# (e.g. PYTEST_*, CI, custom DJANGO_SETTINGS_MODULE override), add the prefix
# here.
_ENV_FORWARD_PREFIXES = ("POSTHOG_", "DEBUG", "TEST", "DATABASE_")


def _send_msg(conn: socket.socket, data: dict) -> None:
    payload = json.dumps(data).encode()
    conn.sendall(struct.pack("!I", len(payload)) + payload)


def _recv_msg(conn: socket.socket) -> dict | None:
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


def _fallback(mode: str, argv: list[str]) -> int:
    """Cold start fallback when daemon isn't running."""
    print("warm-django: daemon not running, falling back to cold start", file=sys.stderr)  # noqa: T201
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

    if mode == "pytest":
        os.execvp("pytest", ["pytest", *argv])
    else:
        os.execvp("python", ["python", "manage.py", *argv])
    return 1  # unreachable


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("manage", "pytest"):
        print("Usage: warm-django <manage|pytest> [args...]", file=sys.stderr)  # noqa: T201
        print("  warm-django manage shell", file=sys.stderr)  # noqa: T201
        print("  warm-django pytest posthog/test/test_utils.py -x", file=sys.stderr)  # noqa: T201
        return 1

    mode = sys.argv[1]
    argv = sys.argv[2:]

    socket_path = get_socket_path()
    t0 = time.perf_counter()

    # Connect to daemon
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.connect(socket_path)
    except (FileNotFoundError, ConnectionRefusedError):
        return _fallback(mode, argv)

    # Send the command
    _send_msg(
        conn,
        {
            "type": "run",
            "mode": mode,
            "argv": argv,
            "env": {k: v for k, v in os.environ.items() if k.startswith(_ENV_FORWARD_PREFIXES)},
        },
    )

    # Stream output
    exit_code = 0
    connected_ms = (time.perf_counter() - t0) * 1000

    while True:
        msg = _recv_msg(conn)
        if msg is None:
            break

        if msg["type"] == "output":
            stream = sys.stdout if msg["stream"] == "stdout" else sys.stderr
            stream.write(msg["data"])
            stream.flush()
        elif msg["type"] == "exit":
            exit_code = msg.get("code", 0)
            break
        elif msg["type"] == "fallback":
            # Daemon is re-execing (e.g. settings change). Run cold this once;
            # the next call hits a freshly-warmed daemon.
            reason = msg.get("reason", "daemon restart")
            print(f"warm-django: {reason} — falling back to cold start", file=sys.stderr)  # noqa: T201
            conn.close()
            return _fallback(mode, argv)

    conn.close()

    total_ms = (time.perf_counter() - t0) * 1000
    # Print timing to stderr so it doesn't pollute command output
    if os.environ.get("warm_django_TIMING"):
        print(f"\nwarm-django: connected in {connected_ms:.0f}ms, total {total_ms:.0f}ms", file=sys.stderr)  # noqa: T201

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
