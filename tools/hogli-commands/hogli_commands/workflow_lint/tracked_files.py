"""Tracked repo files, read the same way from a full or a sparse checkout.

CI runs the lint from a sparse, blobless checkout. A check that tests the disk
for a file the sparse set left out would read it as absent and pass without
looking at it. A skip-worktree entry is a tracked file all the same, so these
reads fall back to its index blob, which git fetches on demand from the
promisor remote. A failed fetch raises and fails the lint, so a narrow checkout
can only make a run slower, never let it pass with less checked.

Outside a sparse checkout, and outside git (fixture trees), this reads the disk
and nothing else.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class TrackedFiles:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._skipped: frozenset[str] | None = None

    def is_file(self, path: str) -> bool:
        return (self.repo_root / path).is_file() or path in self._skip_worktree()

    def is_dir(self, path: str) -> bool:
        prefix = f"{path.rstrip('/')}/"
        return (self.repo_root / path).is_dir() or any(entry.startswith(prefix) for entry in self._skip_worktree())

    def read_text(self, path: str) -> str:
        try:
            return (self.repo_root / path).read_text(encoding="utf-8")
        except OSError:
            if path not in self._skip_worktree():
                raise
        return subprocess.run(
            ["git", "cat-file", "blob", f":{path}"],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            encoding="utf-8",
        ).stdout

    def _skip_worktree(self) -> frozenset[str]:
        if self._skipped is None:
            try:
                listing = subprocess.run(
                    ["git", "ls-files", "-t", "-z"],
                    cwd=self.repo_root,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            except (OSError, subprocess.CalledProcessError):
                listing = ""
            self._skipped = frozenset(entry[2:] for entry in listing.split("\0") if entry.startswith("S "))
        return self._skipped


__all__ = ["TrackedFiles"]
