from __future__ import annotations

from pathlib import Path

from hogli_commands.git_dirs import git_common_dir


def test_git_common_dir_resolves_a_worktree_to_the_shared_object_store(tmp_path: Path) -> None:
    # Packs, the commit-graph and the maintenance lock live in the shared .git, not
    # in the worktree's private directory. A wrong result makes every check pass on
    # a broken repo.
    common = tmp_path / "main" / ".git"
    (common / "worktrees" / "feature").mkdir(parents=True)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {common / 'worktrees' / 'feature'}\n")

    assert git_common_dir(worktree) == common


def test_git_common_dir_handles_a_plain_checkout_and_a_non_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    (plain / ".git").mkdir(parents=True)
    assert git_common_dir(plain) == plain / ".git"

    not_a_repo = tmp_path / "nope"
    not_a_repo.mkdir()
    assert git_common_dir(not_a_repo) is None


def test_git_common_dir_resolves_a_relative_worktree_pointer(tmp_path: Path) -> None:
    # Git writes this pointer relative to the worktree in some layouts. Resolving it
    # against the process working directory finds the wrong object store, or none.
    common = tmp_path / "main" / ".git"
    (common / "worktrees" / "feature").mkdir(parents=True)
    worktree = tmp_path / "feature"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../main/.git/worktrees/feature\n")

    assert git_common_dir(worktree) == common.resolve()


def test_git_common_dir_rejects_a_dangling_worktree_pointer(tmp_path: Path) -> None:
    worktree = tmp_path / "feature"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {tmp_path / 'gone' / '.git' / 'worktrees' / 'feature'}\n")

    assert git_common_dir(worktree) is None
