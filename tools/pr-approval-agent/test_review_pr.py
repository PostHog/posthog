"""Tests for the review_pr.py output format."""

import sys

import pytest
from unittest.mock import MagicMock

# review_pr.py is a uv-script; its `claude_agent_sdk` dep is installed by
# `uv run`, not the test venv. Stub the modules reviewer.py imports from.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import review_pr  # noqa: E402
from github import PRData  # noqa: E402
from review_pr import GateResult, Pipeline  # noqa: E402


def _fake_pr(head_sha: str) -> PRData:
    return PRData(
        number=1,
        repo="PostHog/posthog",
        title="test",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
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


class _TurnLimitReviewer:
    """Stand-in for Reviewer that hits the max turns limit."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def review(self, *args: object, **kwargs: object) -> dict:
        raise RuntimeError("Claude Code returned an error result: Reached maximum number of turns (5)")


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
        # Retryable errors should mention infrastructure
        assert "infrastructure" in pipeline.reviewer_output["reasoning"]


@pytest.mark.parametrize(
    "gate_verdict, expected_final",
    [
        ("PENDING", "ERROR"),
        ("AUTO-APPROVED", "ERROR"),
        ("DENIED", "REFUSED"),
    ],
)
def test_turn_limit_error_not_retried(monkeypatch: pytest.MonkeyPatch, gate_verdict: str, expected_final: str) -> None:
    """A turn-limit error is non-retryable and should give a clear message
    about complexity rather than blaming infrastructure. When gates DENIED,
    the deterministic denial still outranks the error."""
    call_count = 0
    original_review = _TurnLimitReviewer.review

    def counting_review(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_review(self, *args, **kwargs)

    monkeypatch.setattr(review_pr, "Reviewer", _TurnLimitReviewer)
    monkeypatch.setattr(_TurnLimitReviewer, "review", counting_review)
    monkeypatch.setattr(review_pr.time, "sleep", lambda _s: None)
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="abc123")
    pipeline.classification = {"tier": "T1-agent", "breadth": "narrow"}
    pipeline.gate_results = [GateResult("deny-list", gate_verdict != "DENIED", "")]

    pipeline._llm_review(gate_verdict)

    # Non-retryable: should only be called once, not retried
    assert call_count == 1
    assert pipeline.final_verdict == expected_final
    if expected_final == "ERROR":
        assert pipeline.reviewer_output is not None
        assert "could not complete its analysis" in pipeline.reviewer_output["reasoning"]
        # Should NOT mention infrastructure/credentials
        assert "infrastructure" not in pipeline.reviewer_output["reasoning"]
        assert "credentials" not in pipeline.reviewer_output["reasoning"]


def test_bot_author_refuses_before_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bot-authored PR is hard-refused before any classification, gate, or
    LLM call — a human applying the stamphog label can't make the agent review
    bot output."""
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)

    bot_pr = _fake_pr(head_sha="abc123")
    bot_pr.author = "mendral-app[bot]"
    bot_pr.author_is_bot = True

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    monkeypatch.setattr(pipeline, "_fetch", lambda: setattr(pipeline, "pr", bot_pr))

    def _fail_classify() -> None:
        raise AssertionError("bot PR must be refused before classification")

    monkeypatch.setattr(pipeline, "_classify", _fail_classify)

    verdict = pipeline.run()

    assert verdict == "REFUSED"
    assert pipeline.reviewer_output is not None
    assert pipeline.reviewer_output["verdict"] == "REFUSE"
    assert "bot" in pipeline.reviewer_output["reasoning"].lower()

    # The workflow always runs with --output-json, so to_dict() must serialize
    # cleanly even though classification was never populated on this path.
    output = pipeline.to_dict()
    assert output["final_verdict"] == "REFUSED"
    assert output["classification"]["tier"] == ""
    assert output["classification"]["breadth"] == ""


# ── In-flight bot review handling ────────────────────────────────


@pytest.mark.parametrize(
    "reactions",
    [
        pytest.param([], id="no-reactions"),
        pytest.param([{"user": "greptile-apps[bot]", "emoji": "👍"}], id="bot-verdict-reaction"),
        pytest.param([{"user": "alice", "emoji": "👀"}], id="human-eyes-not-waited-on"),
    ],
)
def test_no_wait_without_in_flight_bot_review(monkeypatch: pytest.MonkeyPatch, reactions: list[dict]) -> None:
    # Waiting on a human 👀 would block for longer than any polling budget —
    # the LLM refuses over those instead — and waiting with nothing in flight
    # would slow every review down.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)
    monkeypatch.setattr(review_pr.time, "sleep", lambda _s: pytest.fail("must not poll"))

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="abc123")
    pipeline.pr.pr_reactions = reactions

    assert pipeline._handle_in_flight_bot_reviews() is None
    assert pipeline.final_verdict == ""


def test_waits_out_bot_eyes_race_then_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reviewer bots swap 👀 for a verdict reaction within minutes; refusing
    # during that window was ~26% of all denials in the week this landed.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)
    monkeypatch.setattr(review_pr.time, "sleep", lambda _s: None)

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pr = _fake_pr(head_sha="abc123")
    pr.pr_reactions = [{"user": "greptile-apps[bot]", "emoji": "👀"}]
    pipeline.pr = pr

    def fake_refetch() -> None:
        pr.pr_reactions = [{"user": "greptile-apps[bot]", "emoji": "👍"}]

    monkeypatch.setattr(pipeline, "_fetch", fake_refetch)

    assert pipeline._handle_in_flight_bot_reviews() is None
    assert pipeline.final_verdict == ""


def test_persistent_bot_eyes_yields_wait_not_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    # WAIT keeps the stamphog label (workflow skips the label-strip for it),
    # so a slow bot review retries on the next push instead of demanding a
    # human re-label — a REFUSE here would reintroduce the race friction.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)
    monkeypatch.setattr(review_pr, "BOT_REVIEW_WAIT_BUDGET_SECONDS", 0)
    monkeypatch.setattr(review_pr.time, "sleep", lambda _s: None)

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="abc123")
    pipeline.pr.pr_reactions = [{"user": "hex-security-app[bot]", "emoji": "👀"}]

    assert pipeline._handle_in_flight_bot_reviews() == "WAIT"
    assert pipeline.final_verdict == "WAIT"
    assert pipeline.reviewer_output is not None
    assert pipeline.reviewer_output["verdict"] == "WAIT"
    assert "hex-security-app[bot]" in pipeline.reviewer_output["reasoning"]

    output = pipeline.to_dict()
    assert output["final_verdict"] == "WAIT"


def test_dep_manifest_pr_gets_t1_scrutiny_not_t0(monkeypatch: pytest.MonkeyPatch) -> None:
    # package.json is .json so the allow-list would classify it T0; manifest
    # scripts execute in CI, so these PRs must keep full T1 review now that
    # the deps deny-list no longer blocks them.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pr = _fake_pr(head_sha="abc123")
    pr.files = [{"filename": "frontend/package.json", "additions": 2, "deletions": 1, "status": "M"}]
    pipeline.pr = pr

    pipeline._classify()

    assert pipeline.classification["tier"] == "T1-agent"
    assert pipeline.classification["dep_manifests_without_lockfile"] == ["frontend/package.json"]
