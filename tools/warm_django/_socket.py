"""Shared socket-path resolver for the warm-django daemon and client.

Both ends derive the same path from the repo root, so a mismatch (e.g. one
side computes a different path) silently falls back to cold start. Keep this
single source of truth.
"""

import os
import hashlib

SOCKET_DIR = "/tmp"


def get_socket_path() -> str:
    repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    h = hashlib.sha256(repo_root.encode()).hexdigest()[:12]
    return os.path.join(SOCKET_DIR, f"warm-django-{h}.sock")
