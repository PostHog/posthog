from __future__ import annotations

import os
import re
import fcntl
import hashlib
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def validate_sha256(value: str | None) -> str:
    if value is None or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError("--sha256 must contain the bundle's 64-character SHA-256 digest from its publisher")
    return value.lower()


def require_private_path(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"Private input and state paths must not be symlinks: {path}")
    resolved = path.resolve()
    directory = resolved if resolved.is_dir() else resolved.parent
    while not directory.exists():
        directory = directory.parent
    repository = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=directory, check=False, capture_output=True, text=True
    )
    if repository.returncode == 0:
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(resolved)],
            cwd=repository.stdout.strip(),
            check=False,
        )
        if ignored.returncode != 0:
            raise ValueError(f"Private fixture data and state must be outside Git or ignored: {resolved}")
    elif "not a git repository" not in repository.stderr:
        raise ValueError("Could not check whether private storage is ignored by Git")
    return resolved


def file_sha256(path: Path) -> str:
    with path.open("rb") as content:
        return hashlib.file_digest(content, "sha256").hexdigest()


@contextmanager
def workspace_lock(workspace: Path) -> Iterator[None]:
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    workspace.chmod(0o700)
    descriptor = os.open(workspace / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another fixture preparation is using this state directory") from error
        yield
