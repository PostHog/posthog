"""Tests for cross-PR approval credit."""

from pathlib import Path

import pytest

import stack_credit
from stack_credit import Approval, change_key, collect_credit

from conftest import commit, git, head, write

_REPO = "PostHog/posthog"
_APPROVED_AT = "2026-01-01T00:00:00Z"


# ── change_key ───────────────────────────────────────────────────


def test_change_key_survives_replay_onto_a_different_parent(repo: Path) -> None:
    git("checkout", "-b", "layer", cwd=repo)
    write(repo, "frontend/src/foo.ts", "export const x = 1")
    original = commit(repo, "layer work")

    git("checkout", "master", cwd=repo)
    write(repo, "docs/note.md", "note")
    commit(repo, "unrelated")
    write(repo, "frontend/src/foo.ts", "export const x = 1")
    replayed = commit(repo, "layer work replayed")

    assert original != replayed
    assert change_key(original, repo) == change_key(replayed, repo)


def test_change_key_differs_when_the_pre_image_differs(repo: Path) -> None:
    write(repo, "frontend/src/foo.ts", "export const x = 1")
    commit(repo, "starting point")
    write(repo, "frontend/src/foo.ts", "export const x = 2")
    from_v1 = commit(repo, "bump")

    git("reset", "--hard", "HEAD~2", cwd=repo)
    write(repo, "frontend/src/foo.ts", "export const x = 99")
    commit(repo, "different starting point")
    write(repo, "frontend/src/foo.ts", "export const x = 2")
    from_v99 = commit(repo, "bump")

    assert change_key(from_v1, repo) != change_key(from_v99, repo)


@pytest.mark.parametrize("kind", ["merge", "empty"])
def test_change_key_is_none_for_uncreditable_commits(repo: Path, kind: str) -> None:
    if kind == "empty":
        git("commit", "--allow-empty", "-m", "empty", cwd=repo)
    else:
        git("checkout", "-b", "side", cwd=repo)
        write(repo, "side.ts", "side")
        commit(repo, "side")
        git("checkout", "master", cwd=repo)
        write(repo, "main.ts", "main")
        commit(repo, "main")
        git("merge", "--no-ff", "side", "-m", "merge side", cwd=repo)

    assert change_key(head(repo), repo) is None


# ── stack walk ───────────────────────────────────────────────────


def _pr(number: int, head_ref: str, base_ref: str, author: str = "alice") -> dict:
    return {
        "number": number,
        "user": {"login": author},
        "head": {"ref": head_ref, "repo": {"full_name": _REPO}},
        "base": {"ref": base_ref},
    }


def _fake_gh(prs: dict[int, dict], timelines: dict[int, list[dict]]):
    def _gh_json(*args: str) -> list | dict:
        endpoint = args[0]
        if endpoint.endswith("/timeline"):
            return timelines.get(int(endpoint.split("/")[-2]), [])
        if endpoint.endswith("/pulls"):
            base = next(a.split("=", 1)[1] for a in args if a.startswith("base="))
            return [pr for pr in prs.values() if pr["base"]["ref"] == base]
        return prs[int(endpoint.rsplit("/", 1)[1])]

    return _gh_json


@pytest.fixture
def stack(repo: Path) -> dict:
    """Two-layer stack: PR 1 on master with a1, PR 2 on PR 1's branch with b1."""
    git("checkout", "-b", "pr-a", cwd=repo)
    write(repo, "frontend/src/a.ts", "export const a = 1")
    a1 = commit(repo, "layer a")
    git("checkout", "-b", "pr-b", cwd=repo)
    write(repo, "frontend/src/b.ts", "export const b = 1")
    b1 = commit(repo, "layer b")
    return {
        "a1": a1,
        "b1": b1,
        "prs": {1: _pr(1, "pr-a", "master"), 2: _pr(2, "pr-b", "pr-a")},
    }


def _collect(repo: Path, stack: dict, approvals: dict[int, str]) -> stack_credit.Credit:
    return collect_credit(
        repo=_REPO,
        pr_number=1,
        own_approval=Approval(sha=stack["a1"], submitted_at=_APPROVED_AT),
        cwd=repo,
        base_ref="master",
        find_approval=lambda _repo, number: (
            Approval(sha=approvals[number], submitted_at=_APPROVED_AT) if number in approvals else None
        ),
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack_credit, "_gh_json", lambda *_: pytest.fail("unstubbed gh api call"))


def test_each_layer_contributes_its_own_commits(repo: Path, stack: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack_credit, "_gh_json", _fake_gh(stack["prs"], {}))
    credit = _collect(repo, stack, {2: stack["b1"]})
    assert credit.change_keys == {change_key(stack["a1"], repo), change_key(stack["b1"], repo)}
    assert credit.approved_tips == (stack["a1"], stack["b1"])


def test_layer_off_the_approved_chain_contributes_nothing(
    repo: Path, stack: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PR 2's approval points at a commit that never sat on top of PR 1's
    # approved commit, so the stack is not the shape credit assumes.
    git("checkout", "-b", "divergent", "master", cwd=repo)
    write(repo, "frontend/src/c.ts", "export const c = 1")
    divergent = commit(repo, "off-chain work")

    monkeypatch.setattr(stack_credit, "_gh_json", _fake_gh(stack["prs"], {}))
    credit = _collect(repo, stack, {2: divergent})
    assert credit.change_keys == {change_key(stack["a1"], repo)}
    assert credit.approved_tips == (stack["a1"],)


def test_third_party_layer_is_ignored(repo: Path, stack: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    # Anyone can open a PR against someone else's branch on a public repo.
    stack["prs"][2]["user"]["login"] = "mallory"
    monkeypatch.setattr(stack_credit, "_gh_json", _fake_gh(stack["prs"], {}))
    credit = _collect(repo, stack, {2: stack["b1"]})
    assert credit.change_keys == {change_key(stack["a1"], repo)}


@pytest.mark.parametrize(
    "retargeted_at,expected_credit",
    [
        ("2026-02-01T00:00:00Z", False),
        ("2025-12-01T00:00:00Z", True),
    ],
)
def test_retarget_after_the_approval_voids_credit(
    repo: Path,
    stack: dict,
    monkeypatch: pytest.MonkeyPatch,
    retargeted_at: str,
    expected_credit: bool,
) -> None:
    timelines = {1: [{"event": "base_ref_changed", "created_at": retargeted_at}]}
    monkeypatch.setattr(stack_credit, "_gh_json", _fake_gh(stack["prs"], timelines))
    credit = _collect(repo, stack, {})
    assert bool(credit.change_keys) is expected_credit
