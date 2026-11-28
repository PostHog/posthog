"""Make hogli in a linked worktree import the worktree's copy of each editable package.

A worktree often borrows the main clone's venv, whose editable installs point at the main clone.
hogli loads its commands from the worktree, so without this module a command runs against packages
from another commit. It is first in ``config.boot_modules``, so it runs before any command imports
one of those packages.
"""

from __future__ import annotations

import os
import sys
import site
from collections.abc import Iterable
from pathlib import Path

from hogli.manifest import REPO_ROOT

from hogli_commands.git_dirs import git_common_dir


def _editable_import_roots(site_dirs: Iterable[str]) -> list[str]:
    # `site` adds an absolute .pth line to sys.path as os.path.abspath(line), so the same form
    # finds that entry in sys.path later.
    roots = []
    for site_dir in site_dirs:
        for pth in sorted(Path(site_dir).glob("*.pth")):
            try:
                lines = pth.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                if os.path.isabs(line.strip()) and os.path.isdir(line.strip()):
                    roots.append(os.path.abspath(line.strip()))
    return roots


def worktree_import_roots(repo_root: Path, site_dirs: Iterable[str]) -> dict[str, str]:
    """Map each editable sys.path entry under the main clone to the same directory in the worktree."""
    if not (repo_root / ".git").is_file():
        return {}
    common_dir = git_common_dir(repo_root)
    if common_dir is None:
        return {}
    main_clone = common_dir.parent
    worktree = repo_root.resolve()
    roots = {}
    for root in _editable_import_roots(site_dirs):
        resolved = Path(root).resolve()
        # Mapping the main clone root would put every top-level repo directory on sys.path.
        if resolved == main_clone or not resolved.is_relative_to(main_clone):
            continue
        ours = worktree / resolved.relative_to(main_clone)
        if ours.is_dir():
            roots[root] = str(ours)
    return roots


def _prefer_worktree_packages() -> None:
    # The swap keeps each entry after the standard library, where the editable install put it.
    # PYTHONPATH stays unset because it would put branch code ahead of the standard library in every
    # child process, including ones on another venv. A nested hogli runs this module again.
    roots = worktree_import_roots(REPO_ROOT, site.getsitepackages())
    if roots:
        sys.path[:] = [roots.get(entry, entry) for entry in sys.path]


_prefer_worktree_packages()
