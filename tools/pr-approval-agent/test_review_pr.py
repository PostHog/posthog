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
        pytest.param(
            [{"user": "greptile-apps[bot]", "emoji": "👀", "created_at": "2020-01-01T00:00:00Z"}],
            id="stale-bot-eyes-from-crashed-reviewer-ignored",
        ),
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


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param("frontend/package.json", id="package-json"),
        pytest.param("common/esbuilder/tsconfig.json", id="tsconfig"),
        pytest.param("setup.cfg", id="setup-cfg"),
    ],
)
def test_dep_manifest_pr_gets_t1_scrutiny_not_t0(monkeypatch: pytest.MonkeyPatch, manifest: str) -> None:
    # Manifests are .json/.cfg so the allow-list would classify them T0 and
    # skip the reviewer entirely — making the scripts/hooks REFUSE guard dead
    # code for exactly the files it exists to check. They must land T1.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pr = _fake_pr(head_sha="abc123")
    pr.files = [{"filename": manifest, "additions": 2, "deletions": 1, "status": "M"}]
    pipeline.pr = pr

    pipeline._classify()

    assert pipeline.classification["tier"] == "T1-agent"
    assert pipeline.classification["dep_manifests_without_lockfile"] == [manifest]


@pytest.mark.parametrize(
    "files, expected_flags",
    [
        pytest.param(
            ["products/warehouse_sources/backend/temporal/data_imports/sources/stripe/auth.py"],
            [],
            id="connector-only-pr-not-flagged",
        ),
        pytest.param(
            [
                "products/warehouse_sources/backend/temporal/data_imports/sources/stripe/auth.py",
                "posthog/api/foo.py",
            ],
            ["auth", "billing"],
            id="mixed-pr-keeps-flags",
        ),
    ],
)
def test_title_flags_respect_exempt_paths(
    monkeypatch: pytest.MonkeyPatch, files: list[str], expected_flags: list[str]
) -> None:
    # A connector-only PR legitimately says "stripe"/"oauth" in its title;
    # flagging it re-creates the friction the connector path exemption
    # exists to remove.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pr = _fake_pr(head_sha="abc123")
    pr.title = "fix(stripe): refresh oauth token before sync"
    pr.files = [{"filename": f, "additions": 2, "deletions": 1, "status": "M"} for f in files]
    pipeline.pr = pr

    pipeline._classify()

    assert pipeline.classification["title_scrutiny_flags"] == expected_flags


def test_gate_denied_pr_skips_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    # A deny-listed PR can't be approved over an in-flight review, so waiting
    # 5 minutes before the inevitable REFUSE is pure runner cost.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)
    monkeypatch.setattr(review_pr.time, "sleep", lambda _s: pytest.fail("gate-denied PR must not wait"))

    class _RefusingReviewer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def review(self, *args: object, **kwargs: object) -> dict:
            return {"verdict": "REFUSE", "reasoning": "gates denied", "risk": "high", "issues": []}

    monkeypatch.setattr(review_pr, "Reviewer", _RefusingReviewer)

    pr = _fake_pr(head_sha="abc123")
    pr.files = [{"filename": ".github/workflows/ci.yml", "additions": 2, "deletions": 1, "status": "M"}]
    pr.pr_reactions = [{"user": "greptile-apps[bot]", "emoji": "👀"}]

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    monkeypatch.setattr(pipeline, "_fetch", lambda: setattr(pipeline, "pr", pr))

    assert pipeline.run() == "REFUSED"


def test_wait_refetch_reclassifies_before_review(monkeypatch: pytest.MonkeyPatch) -> None:
    # The wait loop refetches the PR; if the author pushed during the wait,
    # gates must run against the new file set, not the pre-wait snapshot.
    monkeypatch.setattr(review_pr, "_POSTHOG_AVAILABLE", False)
    monkeypatch.setattr(review_pr.time, "sleep", lambda _s: None)

    class _ApprovingReviewer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def review(self, *args: object, **kwargs: object) -> dict:
            return {"verdict": "APPROVE", "reasoning": "ok", "risk": "low", "issues": []}

    monkeypatch.setattr(review_pr, "Reviewer", _ApprovingReviewer)

    initial = _fake_pr(head_sha="abc123")
    initial.files = [{"filename": "docs/readme.md", "additions": 1, "deletions": 0, "status": "M"}]
    initial.pr_reactions = [{"user": "greptile-apps[bot]", "emoji": "👀"}]

    refetched = _fake_pr(head_sha="def456")
    refetched.files = [{"filename": ".github/workflows/ci.yml", "additions": 2, "deletions": 1, "status": "M"}]
    refetched.pr_reactions = []

    fetches = iter([initial, refetched])

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    monkeypatch.setattr(pipeline, "_fetch", lambda: setattr(pipeline, "pr", next(fetches)))

    verdict = pipeline.run()

    assert verdict == "REFUSED"
    assert pipeline.classification["deny_categories"] == ["infra_cicd"]
