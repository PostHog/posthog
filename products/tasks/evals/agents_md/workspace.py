import subprocess
from contextlib import AbstractContextManager
from pathlib import Path

from products.tasks.evals.golden_prs.workspace import GIT_TIMEOUT_SECONDS, checkout_tree


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT_SECONDS
    ).stdout


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
