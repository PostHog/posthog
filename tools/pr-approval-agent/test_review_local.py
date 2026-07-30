"""Tests for the offline review entrypoint's context handling."""

import sys
from datetime import UTC, datetime

from unittest.mock import MagicMock

# review_local pulls in review_pr, whose reviewer.py imports claude_agent_sdk (installed by
# `uv run`, not the test venv). Stub it before importing.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import review_local  # noqa: E402
from review_pr import Pipeline  # noqa: E402


def _review(login: str, state: str, head_sha: str, body: str = "") -> dict:
    return {
        "user": {"login": login, "type": "User"},
        "author_association": "MEMBER",
        "state": state,
        "commit_id": head_sha,
        "submitted_at": "2026-07-15T00:00:00Z",
        "body": body,
    }


def test_commented_reviews_are_dropped_offline(monkeypatch) -> None:
    # The hosted context has no inline review threads, so a bare COMMENTED review at head carries no
    # readable feedback. If it reached PRData, _summarize_assurance would surface its author as a
    # current-head reviewer — reading as independent assurance for feedback nobody can see. It must be
    # filtered; APPROVED and CHANGES_REQUESTED (which the prerequisite gate needs) must survive.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    head_sha = "abc123"
    context = {
        "repo": "PostHog/posthog",
        "head_sha": head_sha,
        "base_sha": "def456",
        "pr": {"number": 1, "title": "t", "state": "OPEN", "user": {"login": "author", "type": "User"}},
        "reviews": [
            _review("carol", "COMMENTED", head_sha),
            _review("dave", "APPROVED", head_sha),
            _review("erin", "CHANGES_REQUESTED", head_sha),
            # A comment-only "hold" carries real human feedback — it must reach the prompt, or the
            # reviewer could approve without ever seeing it.
            _review("frank", "COMMENTED", head_sha, body="Hold off, migration plan pending."),
        ],
    }

    pr = review_local._build_pr_data(context)

    assert "carol" not in {r["user"] for r in pr.reviews}
    assert "frank" in {r["user"] for r in pr.reviews}

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = pr
    assurance = pipeline._summarize_assurance()
    # frank's comment is visible feedback, so counting him as a current-head commenter is factual;
    # carol's bare state must not appear (unseen feedback never reads as assurance).
    assert assurance["head_commented_users"] == ["frank"]
    assert assurance["head_approvals"] == ["dave"]


def test_ownership_summary_preserves_individual_owners() -> None:
    # Individuals-only ownership (team_count == 0) used to collapse to "no owned paths touched",
    # hiding the owner handles from the reviewer prompt — the LLM would approve instead of routing
    # to the named owner. Mirrors _summarize_ownership's emptiness rule.
    assert review_local._ownership_summary({"teams": [], "individuals": ["@a-handle"]}) == "touches @a-handle"
    assert review_local._ownership_summary({"teams": ["org/devex"], "individuals": ["@a-handle"]}) == (
        "touches org/devex, @a-handle"
    )
    assert review_local._ownership_summary({"teams": [], "individuals": []}) == "no owned paths touched"


def test_fresh_trusted_bot_eyes_reach_pr_data_and_flag_in_flight(monkeypatch) -> None:
    # The hosted context now carries raw PR reactions; a fresh 👀 from an allowlisted reviewer bot
    # must reach PRData so the offline WAIT check can fire — hard-coding pr_reactions=[] meant
    # stamphog could approve while another required reviewer was still mid-review. Untrusted
    # reactors must be dropped (anyone can react on a public PR).
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    context = {
        "repo": "PostHog/posthog",
        "head_sha": "abc123",
        "base_sha": "def456",
        "pr": {"number": 1, "title": "t", "state": "OPEN", "user": {"login": "author", "type": "User"}},
        "pr_reactions": [
            {"user": "greptile-apps[bot]", "content": "eyes", "created_at": now_iso},
            {"user": "random-account", "content": "eyes", "created_at": now_iso},
        ],
    }

    pr = review_local._build_pr_data(context)

    assert [r["user"] for r in pr.pr_reactions] == ["greptile-apps[bot]"]
    assert pr.pr_reactions[0]["emoji"] == "👀"

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = pr
    assert pipeline._in_flight_bot_reviewers() == ["greptile-apps[bot]"]
