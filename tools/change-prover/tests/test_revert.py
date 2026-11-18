import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from change_prover import (
    cli,
    prove as prover,
    prove_revert,
)
from change_prover.core import revert
from change_prover.core.policy import Refused
from change_prover.core.revert import Commit, RevertMergeFailed

REPOSITORY = "PostHog/posthog"
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
C, D, M = "c" * 40, "d" * 40, "e" * 40


def merged(sha: str = C, base: str = "master", days: int = 1) -> dict:
    merged_at = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"merged_at": merged_at, "base": {"ref": base}, "merge_commit_sha": sha}


def check_merged(pulls: list[dict]) -> None:
    revert.check_merge_window(revert.merge_time(pulls, C, "master"), NOW)


@pytest.mark.parametrize(
    ("check", "reason"),
    [
        (lambda: revert.reverted_commit(["Fix a thing"]), None),
        (lambda: revert.reverted_commit([f"Revert x\n\nThis reverts commit {C}.", f"This reverts commit {C}."]), None),
        (
            lambda: revert.reverted_commit([f"This reverts commit {C}.", f"This reverts commit {D}."]),
            "reverts 2 commits",
        ),
        (lambda: revert.listed_messages({"commits": [], "total_commits": 1}), "more commits"),
        (lambda: revert.check_in_merge_base({"status": "ahead"}), None),
        (lambda: revert.check_in_merge_base({"status": "identical"}), None),
        (lambda: revert.check_in_merge_base({"status": "diverged"}), "not in the merge base"),
        (lambda: revert.check_in_merge_base({"status": "behind"}), "not in the merge base"),
        (lambda: revert.check_in_merge_base(None), "not in this repository"),
        (lambda: check_merged([merged(days=29)]), None),
        (lambda: check_merged([merged(days=31)]), "more than 30 days ago"),
        (lambda: check_merged([]), "no single merged pull request"),
        (lambda: check_merged([merged(base="release")]), "no single merged pull request"),
        (lambda: check_merged([merged(sha=D)]), "no single merged pull request"),
        (lambda: check_merged([{**merged(), "merged_at": None}]), "no single merged pull request"),
        (lambda: revert.check_reverted_commit(Commit((D,), "Fix a thing\n")), None),
        (lambda: revert.check_reverted_commit(Commit((), "Initial commit\n")), "root commit"),
        (lambda: revert.check_reverted_commit(Commit((D, M), "Merge\n")), "merge commit"),
        (
            lambda: revert.check_reverted_commit(Commit((D,), f"Revert\n\nThis reverts commit {D}.\n")),
            "itself a revert",
        ),
        (lambda: revert.merged_tree(1, f"{M}\n".encode()), "does not revert cleanly"),
        (lambda: revert.check_head_tree(M, D), "differs from a clean revert"),
        (lambda: revert.check_changes([]), "changes no file"),
    ],
)
def test_revert_rules(check: Callable[[], object], reason: str | None) -> None:
    if reason is None:
        check()
    else:
        with pytest.raises(Refused, match=reason):
            check()


@pytest.mark.parametrize(("returncode", "stdout"), [(128, b""), (0, b"not a tree\n")])
def test_a_failed_merge_is_an_error_and_not_a_refusal(returncode: int, stdout: bytes) -> None:
    with pytest.raises(RevertMergeFailed):
        revert.merged_tree(returncode, stdout)


def test_parse_commit_reads_parents_that_a_shallow_fetch_hides() -> None:
    raw = f"tree {M}\nparent {C}\nparent {D}\nauthor a <a@example.com> 1 +0000\n\nMerge\n\nbody\n".encode()

    assert revert.parse_commit(raw) == Commit((C, D), "Merge\n\nbody\n")


def test_a_malformed_reverted_commit_handover_is_refused() -> None:
    env = {"HEAD_SHA": "a" * 40, "WORKFLOW_SHA": "b" * 40, "PULL_REQUEST": "1", "MERGE_BASE": M, "REVERTED": "C" * 40}
    with pytest.raises(Refused, match="not a commit id"):
        cli.revert_prove_request(env)


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir()
        self.git("init", "-q", "-b", "master")
        self.git("config", "uploadpack.allowAnySHA1InWant", "true")

    def git(self, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        command = ["git", "-c", "core.hooksPath=/dev/null", *args]
        return subprocess.run(command, cwd=self.path, check=True, capture_output=True, env=env).stdout.decode()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def commit(self, message: str, files: dict[str, str]) -> str:
        for name, text in files.items():
            (self.path / name).parent.mkdir(parents=True, exist_ok=True)
            (self.path / name).write_text(text)
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)
        return self.head()

    def revert(self, sha: str, *flags: str) -> str:
        self.git("revert", "--no-edit", *flags, sha)
        return self.head()


class RepoGitHub(prover.GitHub):
    """Answers the API calls the revert lane makes from a real repository."""

    def __init__(self, repo: Repo, head: str, merged_days: int, pusher: int) -> None:
        super().__init__(REPOSITORY, "token")
        self.repo, self.head, self.merged_days, self.pusher = repo, head, merged_days, pusher

    def get(self, path: str) -> Any:
        if path.startswith("activity?"):
            return [{"after": self.head, "actor": {"id": self.pusher}}]
        if path.startswith(f"commits/{self.head}/pulls"):
            head = {"sha": self.head, "ref": "pr", "repo": {"full_name": REPOSITORY}}
            return [{"number": 7, "state": "open", "user": {"id": 1}, "base": {"ref": "master"}, "head": head}]
        if path.startswith("commits/"):
            return [merged(sha=path.split("/")[1], days=self.merged_days)]
        assert path.startswith(f"compare/master...{self.head}")
        base = self.repo.git("merge-base", "master", self.head).strip()
        messages = self.repo.git("log", "--format=%B%x00", f"{base}..{self.head}").split("\0")
        commits = [{"commit": {"message": text.strip("\n")}} for text in messages if text.strip()]
        return {"merge_base_commit": {"sha": base}, "commits": commits, "total_commits": len(commits)}

    def find(self, path: str) -> Any | None:
        reverted, merge_base = path.removeprefix("compare/").partition("?")[0].split("...")
        is_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", reverted, merge_base], cwd=self.repo.path, capture_output=True
        )
        return {"status": "ahead" if is_ancestor.returncode == 0 else "diverged"}


def clean_revert(repo: Repo, shas: dict[str, str]) -> str:
    repo.git("switch", "-q", "-c", "pr")
    return repo.revert(shas["C"])


def revert_after_master_moved(repo: Repo, shas: dict[str, str]) -> str:
    repo.commit("Change b", {"b.txt": "moved\n"})
    return clean_revert(repo, shas)


def revert_with_an_extra_change(repo: Repo, shas: dict[str, str]) -> str:
    clean_revert(repo, shas)
    return repo.commit("Sneak in a change", {"b.txt": "extra\n"})


def conflicting_revert(repo: Repo, shas: dict[str, str]) -> str:
    repo.commit("Edit the same line", {"a.txt": "1\nTHREE\n3\n"})
    repo.git("switch", "-q", "-c", "pr")
    return repo.commit(f"Revert change a\n\nThis reverts commit {shas['C']}.", {"a.txt": "1\n2\n3\n"})


def reverted_merge_commit(repo: Repo, shas: dict[str, str]) -> str:
    repo.git("switch", "-q", "-c", "side")
    repo.commit("Side change", {"b.txt": "side\n"})
    repo.git("switch", "-q", "master")
    repo.git("merge", "-q", "--no-ff", "-m", "Merge side", "side")
    merge = repo.head()
    repo.git("switch", "-q", "-c", "pr")
    return repo.revert(merge, "-m", "1")


def revert_of_a_revert(repo: Repo, shas: dict[str, str]) -> str:
    first = repo.revert(shas["C"])
    repo.git("switch", "-q", "-c", "pr")
    return repo.revert(first)


def two_reverted_commits(repo: Repo, shas: dict[str, str]) -> str:
    second = repo.commit("Change b", {"b.txt": "second\n"})
    repo.git("switch", "-q", "-c", "pr")
    repo.revert(second)
    return repo.revert(shas["C"])


def no_revert_line(repo: Repo, shas: dict[str, str]) -> str:
    repo.git("switch", "-q", "-c", "pr")
    return repo.commit("Revert-ish title, plain change", {"b.txt": "plain\n"})


def revert_with_master_merged_in(repo: Repo, shas: dict[str, str]) -> str:
    clean_revert(repo, shas)
    repo.git("switch", "-q", "master")
    repo.commit("Change b", {"b.txt": "later\n"})
    repo.git("switch", "-q", "pr")
    repo.git("merge", "-q", "--no-edit", "master")
    return repo.head()


@pytest.mark.parametrize(
    ("build", "merged_days", "pusher", "expected"),
    [
        (clean_revert, 1, 1, ["a.txt"]),
        (revert_after_master_moved, 1, 1, ["a.txt"]),
        (revert_with_master_merged_in, 1, 1, ["a.txt"]),
        (revert_with_an_extra_change, 1, 1, "differs from a clean revert"),
        (conflicting_revert, 1, 1, "does not revert cleanly"),
        (reverted_merge_commit, 1, 1, "is a merge commit"),
        (revert_of_a_revert, 1, 1, "itself a revert"),
        (two_reverted_commits, 1, 1, "reverts 2 commits"),
        (clean_revert, 31, 1, "more than 30 days ago"),
        (no_revert_line, 1, 1, None),
        # Someone else pushed the revert onto the author's branch, for example onto a Renovate PR.
        (clean_revert, 1, 42, "not pushed by the pull request author"),
    ],
)
def test_the_revert_proof_on_a_real_repository(
    tmp_path: Path,
    build: Callable[[Repo, dict[str, str]], str],
    merged_days: int,
    pusher: int,
    expected: list[str] | str | None,
) -> None:
    upstream = Repo(tmp_path / "upstream")
    issuer = upstream.commit(
        "Add the prover",
        {"tools/change-prover/issuer.yml": "paths:\n  - tools/change-prover/\n", "a.txt": "1\n2\n3\n", "b.txt": "x\n"},
    )
    shas = {"C": upstream.commit("Change a", {"a.txt": "1\nTWO\n3\n"})}
    head = build(upstream, shas)
    runner = Repo(tmp_path / "runner")
    runner.git("remote", "add", "origin", upstream.path.as_uri())
    runner.git("fetch", "-q", "--depth=1", "origin", issuer)
    git = prover.Git(runner.path)

    def proof() -> prover.Proof | None:
        request = prover.IdentifyRequest(REPOSITORY, "master", head)
        found = prove_revert.identify(request, RepoGitHub(upstream, head, merged_days, pusher), NOW)
        assert found is not None
        if found.reverted is None:
            return None
        return prove_revert.prove(prove_revert.RevertProveRequest(head, issuer, found.merge_base, found.reverted), git)

    if isinstance(expected, str):
        with pytest.raises(Refused, match=expected):
            proof()
        return
    proved = proof()
    if expected is None:
        assert proved is None
        return
    assert proved == prover.Proof(
        expected, {"tools/change-prover/": upstream.git("rev-parse", f"{issuer}:tools/change-prover").strip()}
    )
