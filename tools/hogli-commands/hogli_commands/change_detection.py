"""Changed-file detection shared by the hogli dev commands.

A thin wrapper over ``git diff`` + ``git status`` so ``hogli build``, ``ci:preflight``,
and ``test --changed`` agree on "what changed" instead of each rolling its own.
``matches_globs`` is the shared fnmatch predicate. CI computes affectedness its own
way (Turbo, snob); this is just the local dev-CLI helper, not a repo-wide authority.
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
