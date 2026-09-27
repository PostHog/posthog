import os
import shutil
import tempfile
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .cases import GoldenPR

COMMIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "golden-pr-eval",
    "GIT_AUTHOR_EMAIL": "golden-pr-eval@example.com",
    "GIT_COMMITTER_NAME": "golden-pr-eval",
    "GIT_COMMITTER_EMAIL": "golden-pr-eval@example.com",
}


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=os.environ | COMMIT_IDENTITY, capture_output=True, text=True, check=check
    )


def _has_commit(repo: Path, ref: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{ref}^{{commit}}", check=False).returncode == 0


def ensure_golden_commits(repo: Path, pr: GoldenPR) -> None:
    """Fetch the merge commit and its parent when the checkout is shallow or on another branch."""
    if _has_commit(repo, pr.merge_commit_sha) and _has_commit(repo, pr.parent_sha):
        return
    _git(repo, "fetch", "--no-tags", "--depth=2", "origin", pr.merge_commit_sha)


def golden_diff(repo: Path, pr: GoldenPR) -> str:
    return _git(repo, "diff", pr.parent_sha, pr.merge_commit_sha).stdout


@contextmanager
def checkout_parent(repo: Path, pr: GoldenPR) -> Iterator[Path]:
    """Yield a fresh git repository holding only the tree at the commit before the PR.

    An archive rather than a worktree, so the agent cannot read the merged PR out of
    the shared object store with `git log` or `git show`.
    """
    workdir = Path(tempfile.mkdtemp(prefix=f"golden-pr-{pr.number}-"))
    try:
        archive = subprocess.Popen(["git", "archive", pr.parent_sha], cwd=repo, stdout=subprocess.PIPE)
        subprocess.run(["tar", "-x", "-C", workdir], stdin=archive.stdout, check=True)
        if archive.wait() != 0:
            raise subprocess.CalledProcessError(archive.returncode, "git archive")
        _git(workdir, "init", "-q")
        _git(workdir, "add", "-A")
        # Plumbing rather than `git commit`, so a commit hook or signing policy on the host cannot interfere.
        tree = _git(workdir, "write-tree").stdout.strip()
        commit = _git(workdir, "commit-tree", tree, "-m", f"posthog at parent of #{pr.number}").stdout.strip()
        _git(workdir, "update-ref", "HEAD", commit)
        yield workdir
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def candidate_diff(workdir: Path) -> str:
    _git(workdir, "add", "-A")
    return _git(workdir, "diff", "--cached").stdout
