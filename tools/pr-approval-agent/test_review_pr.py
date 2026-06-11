"""Tests for the review_pr.py output format."""

import sys

import pytest
from unittest.mock import MagicMock

# review_pr.py is a uv-script; its `claude_agent_sdk` dep is installed by
# `uv run`, not the test venv. Stub the modules reviewer.py imports from.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import reviewer as reviewer_mod  # noqa: E402
import review_pr  # noqa: E402
from github import PRData  # noqa: E402
from review_pr import GateResult, Pipeline  # noqa: E402


def _fake_pr(head_sha: str, base_ref: str = "master") -> PRData:
    return PRData(
        number=1,
        repo="PostHog/posthog",
        title="test",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
        base_ref=base_ref,
        base_sha="def456",
        head_sha=head_sha,
        files=[],
        reviews=[],
        review_comments=[],
        check_runs=[],
    )


def test_to_dict_includes_head_sha() -> None:
    """The post-review workflow step reads head_sha from the JSON output to
    lock the resulting GitHub review to the sha the LLM actually saw — see
    `.github/workflows/pr-approval-agent.yml`'s "Post review" step."""
    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="07dfeff14d95be1247e4c8c1065fd958a367389e")
    pipeline.classification = {"tier": "T1-trivial", "breadth": "narrow"}
    pipeline.gate_results = []
    pipeline.reviewer_output = None
    pipeline.final_verdict = "APPROVED"

    output = pipeline.to_dict()

    assert output["head_sha"] == "07dfeff14d95be1247e4c8c1065fd958a367389e"


class _RaisingReviewer:
    """Stand-in for Reviewer whose LLM call always fails (backend down)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def review(self, *args: object, **kwargs: object) -> dict:
        raise RuntimeError("Claude Code returned an error result: success")


@pytest.mark.parametrize(
    "gate_verdict, expected_final",
    [
        ("PENDING", "ERROR"),
        ("AUTO-APPROVED", "ERROR"),
        ("DENIED", "REFUSED"),
    ],
)
def test_backend_failure_yields_error_except_when_gates_deny(
    monkeypatch: pytest.MonkeyPatch, gate_verdict: str, expected_final: str
) -> None:
    """A failed LLM call must surface as ERROR (label retained) unless gates
    already DENIED — a deterministic denial outranks an unavailable reviewer."""
    monkeypatch.setattr(review_pr, "Reviewer", _RaisingReviewer)
    monkeypatch.setattr(review_pr.time, "sleep", lambda _s: None)
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="abc123")
    pipeline.classification = {"tier": "T1-agent", "breadth": "narrow"}
    pipeline.gate_results = [GateResult("deny-list", gate_verdict != "DENIED", "")]

    pipeline._llm_review(gate_verdict)

    assert pipeline.final_verdict == expected_final
    if expected_final == "ERROR":
        assert pipeline.reviewer_output is not None
        assert pipeline.reviewer_output["verdict"] == "ERROR"


class _FakeCompleted:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def test_pr_head_worktree_yields_path_and_cleans_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """On success the context manager yields the worktree path and removes it on exit."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
        calls.append(cmd)
        return _FakeCompleted(0)

    monkeypatch.setattr(review_pr.subprocess, "run", fake_run)

    pipeline = Pipeline(pr_number=42, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="cafe123")

    with pipeline._pr_head_worktree() as explore_root:
        assert explore_root is not None
        assert "pr-review-42-" in explore_root.name
        add = next(c for c in calls if "add" in c)
        assert "--detach" in add and "cafe123" in add

    # Cleanup ran with --force after the block exited.
    remove = next(c for c in calls if "remove" in c)
    assert "--force" in remove


def test_pr_head_worktree_falls_back_to_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If worktree creation fails, yield None (review from master) and skip removal."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
        calls.append(cmd)
        return _FakeCompleted(1, stderr="fatal: invalid reference")

    monkeypatch.setattr(review_pr.subprocess, "run", fake_run)

    pipeline = Pipeline(pr_number=7, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="deadbeef")

    with pipeline._pr_head_worktree() as explore_root:
        assert explore_root is None

    # No worktree was created, so none is removed.
    assert not any("remove" in c for c in calls)


def test_reviewer_explore_root_defaults_to_repo_root() -> None:
    from pathlib import Path

    repo = Path("/repo")
    assert reviewer_mod.Reviewer(repo).explore_root == repo
    other = Path("/tmp/wt")
    assert reviewer_mod.Reviewer(repo, explore_root=other).explore_root == other


@pytest.mark.parametrize(
    "base_ref, expect_stack_note",
    [
        ("master", False),
        ("query-validations", True),
    ],
)
def test_reviewer_prompt_stack_note(base_ref: str, expect_stack_note: bool) -> None:
    """A stacked PR (base != master) gets a note telling the agent that
    parent-PR symbols resolve in the tree and aren't missing."""
    from pathlib import Path

    reviewer = reviewer_mod.Reviewer(Path("/repo"))
    pr = _fake_pr(head_sha="abc123", base_ref=base_ref)
    classification = {"tier": "T1-agent", "t1_subclass": "T1b-small", "breadth": "single-area", "commit_type": "feat"}
    gate_context = {"gate_verdict": "PENDING", "gates": []}

    prompt = reviewer._build_review_prompt(pr, classification, gate_context, Path("/tmp/diff.patch"))

    assert ("Stacked PR" in prompt) is expect_stack_note
    if expect_stack_note:
        assert base_ref in prompt
