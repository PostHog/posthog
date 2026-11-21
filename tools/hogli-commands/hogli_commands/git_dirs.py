from __future__ import annotations

from pathlib import Path


def git_common_dir(repo_root: Path) -> Path | None:
    """Return the shared .git directory of the checkout at ``repo_root``, reading files instead of running git.

    In a linked worktree ``.git`` is a file that points at ``<common>/worktrees/<name>``.
    """
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        return None
    try:
        line = dot_git.read_text().strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    worktree_dir = Path(line.split(":", 1)[1].strip())
    # Git writes this pointer relative to the worktree in some layouts.
    if not worktree_dir.is_absolute():
        worktree_dir = repo_root / worktree_dir
    try:
        worktree_dir = worktree_dir.resolve(strict=True)
    except OSError:
        return None  # Dangling pointer. Treat the tree as no repo at all.
    # <common>/worktrees/<name> -> <common>
    if worktree_dir.parent.name == "worktrees":
        return worktree_dir.parent.parent
    return worktree_dir
