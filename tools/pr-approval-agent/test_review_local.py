"""Tests for the offline review entrypoint's context handling."""

import sys
from datetime import UTC, datetime
from typing import Any

import pytest
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


def _thread_context(review_threads: list[dict]) -> dict:
    return {
        "repo": "PostHog/posthog",
        "head_sha": "abc123",
        "base_sha": "def456",
        "pr": {"number": 1, "title": "t", "state": "OPEN", "user": {"login": "author", "type": "User"}},
        "review_threads": review_threads,
    }


def _thread_comment(author: str, body: str, *, association: str = "MEMBER", is_bot: bool = False) -> dict:
    return {"author": author, "author_association": association, "author_is_bot": is_bot, "body": body}


def test_unresolved_review_threads_reach_the_prompt_and_resolved_are_dropped(monkeypatch) -> None:
    # The hosted context now carries inline review threads. Only UNRESOLVED threads must flow into
    # review_comments (which the reviewer prompt renders) — an unresolved inline "do not merge" is the
    # blocker the reviewer must see; a resolved thread is settled noise that would dilute the signal.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    context = _thread_context(
        [
            {
                "is_resolved": False,
                "is_outdated": False,
                "path": "posthog/api/insight.py",
                "line": 42,
                "comments": [_thread_comment("maintainer", "this is wrong, do not merge")],
            },
            {
                "is_resolved": True,
                "is_outdated": False,
                "path": "posthog/api/other.py",
                "line": 7,
                "comments": [_thread_comment("maintainer", "was wrong, now fixed")],
            },
        ]
    )

    pr = review_local._build_pr_data(context)

    assert [c["user"] for c in pr.review_comments] == ["maintainer"]
    assert pr.review_comments[0]["body"] == "this is wrong, do not merge"
    assert pr.review_comments[0]["path"] == "posthog/api/insight.py"
    assert pr.review_comments[0]["line"] == 42
    assert all("now fixed" not in c["body"] for c in pr.review_comments)


@pytest.mark.parametrize(
    "author,association,is_bot,expect_kept",
    [
        pytest.param("alice", "MEMBER", False, True, id="trusted-member-kept"),
        pytest.param("greptile-apps[bot]", "NONE", True, True, id="bot-reviewer-kept"),
        # A drive-by external commenter must not reach the prompt: a fake maintainer hold is both
        # griefable and forgeable — the same trust gate as reviews and discussion.
        pytest.param("outsider", "NONE", False, False, id="untrusted-external-dropped"),
        # Stamphog's own prior inline comments feed back as third-party claims about a stale
        # snapshot — later runs suspect impersonation and refuse forever.
        pytest.param("stamphog[bot]", "NONE", True, False, id="own-comment-dropped"),
    ],
)
def test_review_thread_comments_pass_the_author_trust_gate(
    monkeypatch, author: str, association: str, is_bot: bool, expect_kept: bool
) -> None:
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    context = _thread_context(
        [
            {
                "is_resolved": False,
                "is_outdated": False,
                "path": "a.py",
                "line": 1,
                "comments": [_thread_comment(author, "a comment", association=association, is_bot=is_bot)],
            }
        ]
    )

    pr = review_local._build_pr_data(context)

    assert ([c["user"] for c in pr.review_comments] == [author]) is expect_kept


def test_multi_comment_thread_counts_as_one_unresolved_thread(monkeypatch) -> None:
    # _summarize_assurance counts unresolved THREADS as comments with in_reply_to_id None — a single
    # chatty 3-comment thread must read as one unresolved thread, not three. Only the true thread
    # root (index 0) may carry in_reply_to_id None.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    context = _thread_context(
        [
            {
                "is_resolved": False,
                "is_outdated": False,
                "path": "a.py",
                "line": 1,
                "comments": [
                    _thread_comment("alice", "root concern"),
                    _thread_comment("author", "pushed a fix"),
                    _thread_comment("alice", "still wrong"),
                ],
            }
        ]
    )

    pr = review_local._build_pr_data(context)

    assert len(pr.review_comments) == 3
    assert [c["in_reply_to_id"] for c in pr.review_comments] == [None, -1, -1]

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = pr
    assert pipeline._summarize_assurance()["unresolved_threads"] == 1


def test_filtered_root_thread_counts_zero_unresolved_threads(monkeypatch) -> None:
    # Parity with the Action: when the true thread root is filtered (untrusted author, or stamphog's
    # own inline finding), the survivors are replies — the thread contributes 0 to unresolved_threads,
    # exactly as the Action's real replyTo ids make it. Treating the first survivor as a root would
    # make hosted stricter than the Action on every maintainer reply to a stamphog finding.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    context = _thread_context(
        [
            {
                "is_resolved": False,
                "is_outdated": False,
                "path": "a.py",
                "line": 1,
                "comments": [
                    _thread_comment("rando", "drive-by root", association="NONE"),
                    _thread_comment("maintainer", "actually a fair point"),
                ],
            }
        ]
    )

    pr = review_local._build_pr_data(context)

    assert [c["user"] for c in pr.review_comments] == ["maintainer"]
    assert pr.review_comments[0]["in_reply_to_id"] == -1

    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = pr
    assert pipeline._summarize_assurance()["unresolved_threads"] == 0


def test_absent_review_threads_key_is_a_clean_no_op(monkeypatch) -> None:
    # The Action runtime doesn't pass review_threads yet, so a context without the key must default to
    # no inline comments rather than crash — the engine parity contract.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    context = {
        "repo": "PostHog/posthog",
        "head_sha": "abc123",
        "base_sha": "def456",
        "pr": {"number": 1, "title": "t", "state": "OPEN", "user": {"login": "author", "type": "User"}},
    }

    pr = review_local._build_pr_data(context)

    assert pr.review_comments == []


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


def _selfdriving_context(self_driving: bool) -> dict:
    context: dict[str, Any] = {
        "repo": "PostHog/posthog",
        "head_sha": "abc123",
        "base_sha": "def456",
        "pr": {
            "number": 9,
            "title": "feat: self-driving fix",
            "state": "OPEN",
            "draft": True,
            "user": {"login": "posthog-code[bot]", "type": "Bot"},
        },
    }
    if self_driving:
        context["self_driving_review"] = True
    return context


def test_bot_authored_context_without_the_flag_is_refused(monkeypatch) -> None:
    # An Action-shaped context (no self_driving_review key) must keep today's hard refusal for bot
    # authors — the flag defaulting open would auto-approve every dependabot/renovate PR the hosted
    # runtime sees.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])

    result = review_local.run(_selfdriving_context(False))

    assert result["final_verdict"] == "REFUSED"
    assert "bot" in result["reviewer"]["reasoning"]


def test_self_driving_flag_reviews_the_bot_authored_draft(monkeypatch) -> None:
    # The carve-out's engine half: with the flag set, the run must get PAST the bot-author refusal
    # AND the draft prerequisite (both would otherwise fire for a self-driving PR, which is a
    # bot-authored draft by construction) and reach the review stage. Classification and gates run
    # for real; only the LLM boundary is stubbed.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    seen: dict = {}

    def fake_llm(self, gate_verdict: str) -> None:
        seen["gate_verdict"] = gate_verdict
        self.final_verdict = "APPROVED"
        self.reviewer_output = {"verdict": "APPROVE", "reasoning": "ok", "risk": "low", "issues": []}

    monkeypatch.setattr(Pipeline, "_llm_review", fake_llm)

    result = review_local.run(_selfdriving_context(True))

    assert result["final_verdict"] == "APPROVED"
    assert seen["gate_verdict"] != "DENIED"
    prerequisites = next(g for g in result["gates"] if g["gate"] == "prerequisites")
    assert prerequisites["passed"] is True  # the draft issue is carved out for this run
    assert result["classification"]["self_driving"] is True  # provenance rides into the output contract
