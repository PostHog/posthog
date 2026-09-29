import os
import subprocess
from contextlib import AbstractContextManager
from pathlib import Path

from products.tasks.evals.golden_prs.workspace import COMMIT_IDENTITY, GIT_TIMEOUT_SECONDS, checkout_tree


def _git(repo: Path, *args: str, input: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=os.environ | COMMIT_IDENTITY,
        input=input,
        capture_output=True,
        text=True,
        check=check,
        timeout=GIT_TIMEOUT_SECONDS,
    )


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
    show the rule that the arm removed.
    """
    blob = _git_out(repo, "hash-object", "-w", "--stdin", input=agents_md).strip()
    entries = [line for line in _git_out(repo, "ls-tree", ref).splitlines() if not line.endswith("\tAGENTS.md")]
    tree = _git_out(repo, "mktree", input="\n".join([*entries, f"100644 blob {blob}\tAGENTS.md"]) + "\n").strip()
    return _git_out(repo, "commit-tree", tree, "-m", "baseline").strip()


def push_commit(repo: Path, remote: str, commit: str, branch: str) -> None:
    _git(repo, "push", "-q", remote, f"{commit}:refs/heads/{branch}")


def delete_branch(repo: Path, remote: str, branch: str) -> None:
    _git(repo, "push", "-q", remote, "--delete", branch, check=False)


def fetch_branch_diff(repo: Path, remote: str, branch: str, base: str) -> str | None:
    """The change on `branch` since `base`, or None when nobody pushed the branch."""
    local_ref = f"refs/agents-md-evals/{branch}"
    fetched = _git(repo, "fetch", "-q", "--no-tags", remote, f"+refs/heads/{branch}:{local_ref}", check=False)
    if fetched.returncode != 0:
        if "couldn't find remote ref" in fetched.stderr:
            return None
        raise subprocess.CalledProcessError(fetched.returncode, "git fetch", fetched.stdout, fetched.stderr)
    try:
        return _git_out(repo, "diff", "--binary", "--src-prefix=a/", "--dst-prefix=b/", base, local_ref)
    finally:
        _git(repo, "update-ref", "-d", local_ref)


def apply_diff(workdir: Path, diff: str) -> None:
    _git(workdir, "apply", "--binary", "--whitespace=nowarn", "-", input=diff)
