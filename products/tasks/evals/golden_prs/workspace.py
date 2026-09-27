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


def _git(cwd: Path, *args: str, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=os.environ | COMMIT_IDENTITY,
        input=input,
        capture_output=True,
        text=True,
        check=check,
    )


def _has_commit(repo: Path, ref: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{ref}^{{commit}}", check=False).returncode == 0


def ensure_golden_commits(repo: Path, pr: GoldenPR) -> None:
    """Fetch the merge commit and its parent when the checkout is shallow or on another branch."""
    if _has_commit(repo, pr.merge_commit_sha) and _has_commit(repo, pr.parent_sha):
        return
    _git(repo, "fetch", "--no-tags", "--depth=2", "origin", pr.merge_commit_sha)


def _diff(cwd: Path, *args: str) -> str:
    # The scorer reads `a/` and `b/` from the diff headers, so a host `diff.mnemonicPrefix`
    # or `diff.noprefix` setting must not change them.
    return _git(cwd, "diff", "--src-prefix=a/", "--dst-prefix=b/", *args).stdout


def golden_diff(repo: Path, pr: GoldenPR) -> str:
    return _diff(repo, pr.parent_sha, pr.merge_commit_sha)


def _restore_export_ignored_files(repo: Path, ref: str, workdir: Path) -> None:
    """Copy the files that `git archive` drops because `.gitattributes` marks them export-ignore.

    That set includes every `.gitignore`, and without those `git add -A` would stage the agent's
    build output into the candidate diff.
    """
    paths = _git(repo, "ls-tree", "-r", "--name-only", ref).stdout.splitlines()
    attributes = _git(repo, "check-attr", f"--source={ref}", "--stdin", "export-ignore", input="\n".join(paths))
    for line in attributes.stdout.splitlines():
        path, _, value = line.rsplit(": ", 2)
        if value == "set":
            target = workdir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True).stdout)


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
        _restore_export_ignored_files(repo, pr.parent_sha, workdir)
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
    return _diff(workdir, "--cached")
