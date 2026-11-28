from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from hogli_commands.worktree_packages import worktree_import_roots


@pytest.fixture
def main_clone(tmp_path: Path, git: Callable[..., str]) -> Path:
    main = tmp_path / "main"
    for package in ("packages/owners-yaml", "tools/hogli/src"):
        (main / package).mkdir(parents=True)
        (main / package / "keep").write_text("")
    git(main, "init", "-q")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "init")
    return main


def _site_dir(tmp_path: Path, *lines: str) -> str:
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    (site_dir / "_editable_impl_packages.pth").write_text("\n".join(lines) + "\n")
    (site_dir / "coverage.pth").write_text("import os; exec('pass')\n")
    return str(site_dir)


@pytest.mark.parametrize("worktree_dir", ["outside", "main/.claude/worktrees/nested"])
def test_a_worktree_imports_its_own_copy_of_each_package_the_main_clone_venv_installs(
    tmp_path: Path, main_clone: Path, git: Callable[..., str], worktree_dir: str
) -> None:
    worktree = tmp_path / worktree_dir
    git(main_clone, "worktree", "add", "-q", "--detach", str(worktree))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    site_dir = _site_dir(
        tmp_path,
        str(main_clone),
        str(main_clone / "packages/owners-yaml"),
        str(main_clone / "tools/hogli/src"),
        str(main_clone / "untracked-only-in-main"),
        str(elsewhere),
        str(worktree / "tools/hogli/src"),
    )
    (main_clone / "untracked-only-in-main").mkdir()

    assert worktree_import_roots(worktree, [site_dir]) == {
        str(main_clone / "packages/owners-yaml"): str(worktree.resolve() / "packages/owners-yaml"),
        str(main_clone / "tools/hogli/src"): str(worktree.resolve() / "tools/hogli/src"),
    }


def test_the_main_clone_keeps_its_editable_installs(tmp_path: Path, main_clone: Path) -> None:
    site_dir = _site_dir(tmp_path, str(main_clone / "packages/owners-yaml"))

    assert worktree_import_roots(main_clone, [site_dir]) == {}
