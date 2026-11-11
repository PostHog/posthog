"""Make a linked worktree import its own copy of each editable workspace package.

A worktree often runs hogli with the main clone's venv. Its editable installs point at the main
clone's files, but hogli loads commands from the worktree, so a command can run against a package
from another commit and fail or skip. Listed first in ``config.boot_modules``, so it runs before
any command imports a workspace package.
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
    # An editable install writes its import root as a bare absolute path line in a .pth file,
    # and `site` adds it to sys.path as os.path.abspath(line). Lines that start with `import` run code.
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
    """Map each sys.path entry that an editable install points into the main clone to the worktree's copy."""
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
        # The main clone root itself would put every top-level repo directory on sys.path.
        if resolved == main_clone or not resolved.is_relative_to(main_clone):
            continue
        ours = worktree / resolved.relative_to(main_clone)
        if ours.is_dir():
            roots[root] = str(ours)
    return roots


def _prefer_worktree_packages() -> None:
    # Each entry keeps its position after site-packages, as the editable install placed it, so a
    # package root cannot shadow the standard library. PYTHONPATH stays unset, because it would put
    # this branch's code ahead of the standard library in child processes, including ones that run
    # another venv. A nested hogli runs this module again.
    roots = worktree_import_roots(REPO_ROOT, site.getsitepackages())
    if roots:
        sys.path[:] = [roots.get(entry, entry) for entry in sys.path]


_prefer_worktree_packages()
