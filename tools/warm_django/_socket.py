"""Shared protocol + socket-path helpers for the warm-django daemon and client.

Both sides need the same socket path (so a mismatch silently falls back to
cold start) and the same length-prefixed JSON wire format. This module is the
single source of truth for both.
"""

import os
import json
import socket
import struct
import hashlib

SOCKET_DIR = "/tmp"


def get_socket_path() -> str:
    repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    h = hashlib.sha256(repo_root.encode()).hexdigest()[:12]
    return os.path.join(SOCKET_DIR, f"warm-django-{h}.sock")


def send_msg(conn: socket.socket, data: dict) -> None:
    """Send a length-prefixed JSON message."""
    payload = json.dumps(data).encode()
    conn.sendall(struct.pack("!I", len(payload)) + payload)


def recv_msg(conn: socket.socket) -> dict | None:
    """Receive a length-prefixed JSON message. Returns None on connection close."""
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
