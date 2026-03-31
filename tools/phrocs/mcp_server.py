#!/usr/bin/env python3
"""Local MCP server for PostHog dev environment process observability.

Both tools query phrocs directly over a Unix domain socket whose path is
derived from the workspace root (CWD), matching the socket phrocs binds.
No file-based intermediary — phrocs tracks status, metrics, and logs in-memory.

Run via Claude Code's .mcp.json (invoked automatically by the MCP client):
  uv run python tools/phrocs/mcp_server.py
"""

from __future__ import annotations

import os
import json
import socket
import hashlib
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "phrocs",
    instructions=(
        "Tools for inspecting the local PostHog dev environment. "
        "Start the dev environment with `./bin/start` before using these tools."
    ),
)


def _socket_path() -> str:
    """Return the phrocs socket path for the current workspace (CWD).

    Mirrors the SocketPathFor logic in tools/phrocs/internal/ipc/server.go so
    both sides agree on the path without any runtime coordination.
    """
    real = os.path.realpath(os.getcwd())
    digest = hashlib.sha256(real.encode()).hexdigest()[:8]
    return f"/tmp/phrocs-{digest}.sock"


_PHROCS_SOCK = _socket_path()


def _query_phrocs(cmd: dict) -> dict | None:
    """Send a command to phrocs via Unix domain socket.

    Returns the parsed response dict, or None if phrocs is not running.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(_PHROCS_SOCK)
            sock.sendall((json.dumps(cmd) + "\n").encode())
            with sock.makefile() as f:
                return json.loads(f.readline())
    except (OSError, json.JSONDecodeError, TimeoutError):
        return None


_NOT_RUNNING = {"error": "phrocs is not running. Start the dev environment with: ./bin/start"}


@mcp.tool()
def get_process_status(process: str = "") -> dict[str, Any]:
    """Get the status of one or all dev environment processes.
    Returns pid (OS process ID), running state, readiness, exit code,
    startup duration, and resource metrics (mem_rss_mb, cpu_percent,
    thread_count, etc.) for each process. Metrics arrive with ~5 seconds.
    Args:
        process: Process name (e.g. 'backend', 'frontend', 'celery-worker').
                 Leave empty to get status for all processes.
    """
    if process:
        result = _query_phrocs({"cmd": "status", "process": process})
        if result is None:
            return {process: _NOT_RUNNING}
        if not result.get("ok"):
            return {process: {"error": result.get("error", "unknown error")}}
        return {process: result}

    result = _query_phrocs({"cmd": "status_all"})
    if result is None:
        return _NOT_RUNNING
    if not result.get("ok"):
        return {"error": result.get("error", "unknown error")}
    return result.get("processes", {})


@mcp.tool()
def get_process_logs(process: str, lines: int = 100, grep: str = "") -> dict[str, Any]:
    """Get recent log output from a dev environment process.
    Reads from phrocs' in-memory scrollback buffer (10,000 lines per process).
    Args:
        process: Process name (e.g. 'backend', 'frontend', 'celery-worker').
        lines: Number of recent lines to return (default 100, max 500).
        grep: Optional regex pattern to filter lines (e.g. 'ERROR', 'warning').
    """
    lines = min(max(lines, 1), 500)
    result = _query_phrocs({"cmd": "logs", "process": process, "lines": lines, "grep": grep or ""})

    if result is None:
        return {"process": process, **_NOT_RUNNING}
    if not result.get("ok"):
        return {"process": process, "error": result.get("error", "unknown error")}

    resp: dict[str, Any] = {
        "process": process,
        "returned_lines": len(result["lines"]),
        "logs": result["lines"],
    }
    if grep:
        resp["grep"] = grep
        resp["total_matched"] = result.get("total_matched", 0)
    resp["buffered"] = result.get("buffered", 0)
    return resp


if __name__ == "__main__":
    mcp.run()
