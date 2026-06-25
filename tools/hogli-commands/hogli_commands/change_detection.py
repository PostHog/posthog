"""What this branch changed — the single source of truth for change detection.

A deep module behind a tiny interface. ``changed_files`` answers "what has the
branch touched" for every consumer (``hogli build`` smart detection, ``ci:preflight``,
``test --changed``); ``matches_globs`` is the shared fnmatch predicate. Callers stop
re-deriving git plumbing and glob loops, so they can't drift apart.
"""

from __future__ import annotations

import fnmatch
import subprocess
from collections.abc import Iterable

import click
from hogli.manifest import REPO_ROOT


def changed_files(against: str = "master") -> list[str]:
    """Files the branch touches vs *against* (merge-base), plus uncommitted/untracked work.

    *against* may be any ref (e.g. ``origin/master``); a bad ref raises so a typo
    can't masquerade as a clean diff. On the base branch itself the diff is just empty.
    """
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{against}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        raise click.UsageError(f"git diff against {against!r} failed: {diff.stderr.strip()}")
    files = {line for line in diff.stdout.splitlines() if line}
    status = subprocess.run(
        ["git", "status", "--porcelain", "--no-renames"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    files.update(line[3:] for line in status.stdout.splitlines() if len(line) > 3)
    return sorted(files)


def matches_globs(path: str, globs: Iterable[str]) -> bool:
    """True if *path* matches any fnmatch glob (``*`` spans ``/``, matching build & CI)."""
    return any(fnmatch.fnmatch(path, glob) for glob in globs)
