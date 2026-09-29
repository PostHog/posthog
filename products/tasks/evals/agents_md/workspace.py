import os
import subprocess
from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path

from products.tasks.evals.golden_prs.workspace import GIT_TIMEOUT_SECONDS, checkout_tree

# Scratch branches start no CI workflow and never get a pull request, which is what the pre-push
# preflight protects. The hook's merge-queue guard still runs.
SCRATCH_PUSH_ENV = {"HOGLI_PREFLIGHT_DISABLED": "1"}


def _git(
    repo: Path, *args: str, input: str | None = None, check: bool = True, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args], cwd=repo, input=input, env=env, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {completed.stderr.strip()}")
    return completed


def _git_out(repo: Path, *args: str, input: str | None = None) -> str:
    return _git(repo, *args, input=input).stdout


def resolve_ref(repo: Path, ref: str) -> str:
    """The commit sha, so a result names the exact tree and AGENTS.md it ran on."""
    return _git_out(repo, "rev-parse", f"{ref}^{{commit}}").strip()


def agents_md_at(repo: Path, ref: str) -> str:
    return _git_out(repo, "show", f"{ref}:AGENTS.md")


def checkout_with_agents_md(repo: Path, ref: str, agents_md: str) -> AbstractContextManager[Path]:
    """A fresh repository at `ref` whose AGENTS.md is `agents_md`, committed as the base so it stays out of the diff.

    CLAUDE.md is a symlink to AGENTS.md in this repository, so one file serves both agents.
    """

    def write_agents_md(workdir: Path) -> None:
        (workdir / "AGENTS.md").write_text(agents_md)

    return checkout_tree(repo, ref, write_agents_md)


def orphan_commit_with_agents_md(repo: Path, ref: str, agents_md: str) -> str:
    """The tree at `ref` with `agents_md` as AGENTS.md, in a commit with no parent.

    A cloud agent clones the branch with its history, and a parent would let `git diff HEAD~1`
    show the rule that the arm removed. The commit takes the author and signing settings of `repo`,
    because a repository that requires verified signatures refuses the push otherwise.
    """
    blob = _git_out(repo, "hash-object", "-w", "--stdin", input=agents_md).strip()
    entries = [line for line in _git_out(repo, "ls-tree", ref).splitlines() if not line.endswith("\tAGENTS.md")]
    tree = _git_out(repo, "mktree", input="\n".join([*entries, f"100644 blob {blob}\tAGENTS.md"]) + "\n").strip()
    # commit-tree ignores commit.gpgsign, so follow it here the way `git commit` would.
    sign = _git(repo, "config", "--type=bool", "commit.gpgsign", check=False).stdout.strip() == "true"
    return _git_out(repo, "commit-tree", *(["-S"] if sign else []), tree, "-m", "baseline").strip()


def push_commit(repo: Path, remote: str, commit: str, branch: str) -> None:
    _git(repo, "push", "-q", remote, f"{commit}:refs/heads/{branch}", env=os.environ | SCRATCH_PUSH_ENV)


def delete_branch(repo: Path, remote: str, branch: str) -> None:
    _git(repo, "push", "-q", remote, "--delete", branch, check=False, env=os.environ | SCRATCH_PUSH_ENV)


def fetch_branch_diff(repo: Path, remote: str, branch: str, base: str) -> str | None:
    """The change on `branch` since `base`, or None when nobody pushed the branch."""
    local_ref = f"refs/agents-md-evals/{branch}"
    fetched = _git(repo, "fetch", "-q", "--no-tags", remote, f"+refs/heads/{branch}:{local_ref}", check=False)
    if fetched.returncode != 0:
        if "couldn't find remote ref" in fetched.stderr:
            return None
        raise RuntimeError(f"git fetch {branch} failed: {fetched.stderr.strip()}")
    try:
        return _git_out(repo, "diff", "--binary", "--src-prefix=a/", "--dst-prefix=b/", base, local_ref)
    finally:
        _git(repo, "update-ref", "-d", local_ref)


def apply_diff(workdir: Path, diff: str) -> None:
    _git(workdir, "apply", "--binary", "--whitespace=nowarn", "-", input=diff)
