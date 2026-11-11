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
import subprocess
from collections.abc import Iterable
from pathlib import Path

from hogli.manifest import REPO_ROOT


def _main_clone(repo_root: Path) -> Path | None:
    if not (repo_root / ".git").is_file():
        return None
    common_dir = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if common_dir.returncode != 0:
        return None
    return Path(common_dir.stdout.strip()).resolve().parent


def _editable_import_roots(site_dirs: Iterable[str]) -> list[Path]:
    # An editable install writes its import root as a bare absolute path line in a .pth file.
    # Lines that start with `import` run code and are never paths.
    roots = []
    for site_dir in site_dirs:
        for pth in sorted(Path(site_dir).glob("*.pth")):
            for line in pth.read_text(encoding="utf-8", errors="replace").splitlines():
                path = Path(line.strip())
                if path.is_absolute() and path.is_dir():
                    roots.append(path.resolve())
    return roots


def worktree_import_roots(repo_root: Path, site_dirs: Iterable[str]) -> list[str]:
    main_clone = _main_clone(repo_root)
    if main_clone is None:
        return []
    roots = []
    for root in _editable_import_roots(site_dirs):
        if not root.is_relative_to(main_clone):
            continue
        ours = repo_root.resolve() / root.relative_to(main_clone)
        if ours.is_dir():
            roots.append(str(ours))
    return roots


def _prefer_worktree_packages() -> None:
    roots = worktree_import_roots(REPO_ROOT, site.getsitepackages())
    if not roots:
        return
    sys.path[:0] = roots
    # Child processes, such as a check that runs pytest or a script, need the same packages.
    os.environ["PYTHONPATH"] = os.pathsep.join([*roots, *filter(None, [os.environ.get("PYTHONPATH")])])


_prefer_worktree_packages()
