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

# A caller's GIT_DIR/GIT_WORK_TREE (or similar) would override `cwd` as the repository these
# subprocesses target, so scrub them rather than trust the ambient environment.
REPO_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)

GIT_TIMEOUT_SECONDS = 120

# A fixed pointer to the baseline commit, independent of HEAD, so a commit the agent makes in
# `workdir` (against instructions) cannot move the commit `candidate_diff` scores against.
BASELINE_REF = "refs/golden-eval/baseline"

# Withheld from any Git subprocess that stages agent-controlled content, so a clean/smudge
# filter the agent configured in .gitattributes/.git/config has nothing to exfiltrate.
SECRET_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")


def _repo_git_env(*, deny_secrets: bool = False) -> dict[str, str]:
    denied = REPO_LOCATION_VARS + (SECRET_ENV_VARS if deny_secrets else ())
    return {key: value for key, value in os.environ.items() if key not in denied} | COMMIT_IDENTITY


def _git(
    cwd: Path, *args: str, check: bool = True, input: str | None = None, deny_secrets: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=_repo_git_env(deny_secrets=deny_secrets),
        input=input,
        capture_output=True,
        text=True,
        check=check,
        timeout=GIT_TIMEOUT_SECONDS,
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
    build output into the candidate diff. Comparing against the extracted tree, rather than
    checking the export-ignore attribute per file, also catches a directory-level rule (like
    `.github/ export-ignore`) that `git check-attr` does not report on the files underneath it.
    """
    entries = _git(repo, "ls-tree", "-r", ref).stdout.splitlines()
    for entry in entries:
        meta, path = entry.split("\t", 1)
        mode, _obj_type, _blob_sha = meta.split()
        target = workdir / path
        # A symlink the archive extracted counts as present even when its target does not exist.
        if target.exists(follow_symlinks=False):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=repo,
            env=_repo_git_env(),
            capture_output=True,
            check=True,
            timeout=GIT_TIMEOUT_SECONDS,
        ).stdout
        if mode == "120000":
            target.symlink_to(content.decode())
        else:
            target.write_bytes(content)
            if mode == "100755":
                target.chmod(target.stat().st_mode | 0o111)


@contextmanager
def checkout_parent(repo: Path, pr: GoldenPR) -> Iterator[Path]:
    """Yield a fresh git repository holding only the tree at the commit before the PR.

    An archive rather than a worktree, so the agent cannot read the merged PR out of
    the shared object store with `git log` or `git show`.
    """
    # A prefix and commit message that carry no PR number, so an agent inspecting its own cwd or
    # `git log` cannot learn which public PR it is meant to reproduce.
    workdir = Path(tempfile.mkdtemp(prefix="golden-pr-"))
    try:
        archive = subprocess.Popen(["git", "archive", pr.parent_sha], cwd=repo, stdout=subprocess.PIPE)
        try:
            try:
                tar_result = subprocess.run(
                    ["tar", "-x", "-C", workdir], stdin=archive.stdout, check=False, timeout=GIT_TIMEOUT_SECONDS
                )
            finally:
                if archive.stdout:
                    archive.stdout.close()
            archive_returncode = archive.wait(timeout=GIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            archive.kill()
            archive.wait()
            raise
        if tar_result.returncode != 0:
            raise subprocess.CalledProcessError(tar_result.returncode, "tar")
        if archive_returncode != 0:
            raise subprocess.CalledProcessError(archive_returncode, "git archive")
        _restore_export_ignored_files(repo, pr.parent_sha, workdir)
        _git(workdir, "init", "-q")
        # Forced: the parent tree can hold a file (like `.envrc`) that a `.gitignore` restored a
        # moment ago now matches, and a plain `add -A` would silently drop it from the baseline.
        _git(workdir, "add", "-f", "-A")
        # Plumbing rather than `git commit`, so a commit hook or signing policy on the host cannot interfere.
        tree = _git(workdir, "write-tree").stdout.strip()
        commit = _git(workdir, "commit-tree", tree, "-m", "baseline").stdout.strip()
        _git(workdir, "update-ref", "HEAD", commit)
        # A ref an agent commit can't move, so candidate_diff can still score against the true
        # parent state even if the agent committed its changes despite being told not to.
        _git(workdir, "update-ref", BASELINE_REF, commit)
        yield workdir
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def candidate_diff(workdir: Path) -> str:
    _git(workdir, "add", "-A", deny_secrets=True)
    baseline = _git(workdir, "rev-parse", "--verify", "--quiet", BASELINE_REF, check=False)
    if baseline.returncode == 0:
        return _diff(workdir, "--cached", BASELINE_REF)
    return _diff(workdir, "--cached")
