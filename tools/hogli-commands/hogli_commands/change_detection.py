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


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def changed_files(against: str | None = None, *, include_worktree: bool = True) -> list[str]:
    """Files the branch touches vs a base ref (merge-base), plus uncommitted/untracked work.

    An explicit *against* raises on a bad ref so a typo can't masquerade as a clean
    diff. The default base tries ``origin/master`` then ``master`` (origin/master is
    what CI diffs against and what the staleness check compares to) and degrades to
    working-tree-only detection when neither exists (single-branch clones, bare
    sandboxes). ``-z`` output keeps paths with spaces/non-ASCII unquoted, and
    ``--untracked-files=all`` lists files inside brand-new directories.

    ``include_worktree=False`` restricts the result to the committed branch diff,
    dropping uncommitted and untracked work — the correct scope for a pre-push gate,
    where only committed changes are actually pushed (and can reach CI). Callers that
    iterate on local edits (``build``, ``test --changed``) keep the default.
    """
    files: set[str] = set()
    for base in [against] if against is not None else ["origin/master", "master"]:
        diff = _git("diff", "--name-only", "-z", f"{base}...HEAD")
        if diff.returncode == 0:
            files.update(path for path in diff.stdout.split("\0") if path)
            break
        if against is not None:
            raise click.UsageError(f"git diff against {against!r} failed: {diff.stderr.strip()}")
    if not include_worktree:
        return sorted(files)
    status = _git("status", "--porcelain", "-z", "--no-renames", "--untracked-files=all")
    if status.returncode != 0:
        # A failed status (e.g. index.lock contention) must not read as "no uncommitted work".
        raise click.UsageError(f"git status failed: {status.stderr.strip()}")
    files.update(entry[3:] for entry in status.stdout.split("\0") if len(entry) > 3)
    return sorted(files)


def matches_globs(path: str, globs: Iterable[str]) -> bool:
    """True if *path* matches any fnmatch glob (``*`` spans ``/``, matching build & CI)."""
    return any(fnmatch.fnmatch(path, glob) for glob in globs)
