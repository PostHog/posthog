"""Tests for the offline review entrypoint's context handling."""

import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

# review_local pulls in review_pr, whose reviewer.py imports claude_agent_sdk (installed by
# `uv run`, not the test venv). Stub it before importing.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import review_pr  # noqa: E402
import review_local  # noqa: E402
from github import CommitProvenance  # noqa: E402
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


def _ownership_pipeline(ownership: dict, author: str = "alice") -> Pipeline:
    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = MagicMock(author=author)
    pipeline.classification = {"ownership": ownership}
    return pipeline


@pytest.mark.parametrize(
    "ownership,author_team_slugs,expected_summary,expected_on_team",
    [
        # Individuals-only ownership (team_count == 0) must not collapse to "no owned paths
        # touched". That summary would hide the owner handles that the reviewer needs for
        # escalations.
        ({"team_count": 0, "teams": [], "individuals": ["@a-handle"]}, set(), "individually owned by @a-handle", False),
        (
            {"team_count": 0, "teams": [], "individuals": ["@alice"]},
            set(),
            "individually owned by @alice (author alice is one of them)",
            False,
        ),
        ({"team_count": 0, "teams": [], "individuals": []}, set(), "no owned paths touched", None),
        (
            {"team_count": 1, "teams": ["org/devex"], "individuals": []},
            set(),
            "touches org/devex; author alice is not on any owning team",
            False,
        ),
        (
            {"team_count": 1, "teams": ["org/devex"], "individuals": []},
            {"devex"},
            "touches org/devex; author alice is on org/devex",
            True,
        ),
        (
            {"team_count": 2, "teams": ["org/a", "org/b"], "individuals": [], "cross_team": True},
            {"a"},
            "touches org/a, org/b; author alice is on org/a; cross-team change",
            True,
        ),
    ],
)
def test_ownership_summary_reflects_author_team_membership(
    ownership: dict, author_team_slugs: set, expected_summary: str, expected_on_team: bool | None
) -> None:
    # author_on_owning_team drives the reviewer prompt's "NOTE: Author is NOT on the owning team",
    # which reads the key with a default of True. An unset key tells the reviewer that every author
    # owns the code that they touched, and the note then never appears on a hosted review.
    pipeline = _ownership_pipeline(ownership)

    review_local._apply_ownership_summary(pipeline, author_team_slugs)

    assert pipeline.classification["ownership_summary"] == expected_summary
    assert pipeline.classification.get("author_on_owning_team") is expected_on_team


def _run_context(files: list[dict], check_runs: list[dict] | None = None) -> dict:
    return {
        "repo": "PostHog/posthog",
        "head_sha": "h" * 40,
        "base_sha": "b" * 40,
        "pr": {
            "number": 1,
            "title": "feat(x): add a column",
            "state": "OPEN",
            "mergeable_state": "clean",
            "user": {"login": "alice", "type": "User"},
        },
        "files": files,
        "check_runs": check_runs or [],
    }


def _api_file(filename: str, status: str = "added") -> dict:
    return {"filename": filename, "additions": 10, "deletions": 0, "status": status, "patch": "@@"}


def test_pending_migration_check_waits_instead_of_refusing(monkeypatch) -> None:
    # A migration PR whose "Migration risk" check has not reported yet matches the deny-list only
    # because the engine cannot tell a safe migration from a risky one. A REFUSED verdict would
    # start the hosted runtime's refusal path, which is a ReviewHog handoff and a trigger-label
    # strip, for a race with CI. WAIT keeps the label and runs the review again on the next push.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    monkeypatch.setattr(review_local, "pr_provenance", lambda *a, **k: None)
    context = _run_context([_api_file("posthog/migrations/0999_add_col.py")])

    result = review_local.run(context)

    assert result["final_verdict"] == "WAIT"
    assert "Migration risk" in result["reviewer"]["reasoning"]


def test_offline_run_carries_commit_provenance(monkeypatch) -> None:
    # pr_provenance reads commit trailers from the checkout and needs no token, so the sandbox can
    # compute it. Without this call, provenance is null on every hosted review, which drops
    # agent-authorship from the evidence bundle and from the stamphog_review_completed
    # properties.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    monkeypatch.setattr(
        review_local,
        "pr_provenance",
        lambda *a, **k: CommitProvenance(
            commit_count=3, agent_commit_count=2, generated_by=("claude",), task_ids=("t-1",)
        ),
    )
    context = _run_context([_api_file("posthog/migrations/0999_add_col.py")])

    result = review_local.run(context)

    assert result["provenance"] == {
        "agent_authored": True,
        "commit_count": 3,
        "agent_commit_count": 2,
        "generated_by": ["claude"],
        "task_ids": ["t-1"],
    }


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
    # Parity with the networked path. When a filter removes the true thread root (untrusted author,
    # or stamphog's own inline finding), the survivors are replies, so the thread contributes 0 to
    # unresolved_threads. The networked path's real replyTo ids produce the same count. Treatment of
    # the first survivor as a root would make the sandbox stricter on every maintainer reply to a
    # stamphog finding.
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
    # A local review_pr.py run does not pass review_threads, so a context without the key must
    # default to no inline comments rather than crash. That is the engine parity contract.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    context = {
        "repo": "PostHog/posthog",
        "head_sha": "abc123",
        "base_sha": "def456",
        "pr": {"number": 1, "title": "t", "state": "OPEN", "user": {"login": "author", "type": "User"}},
    }

    pr = review_local._build_pr_data(context)

    assert pr.review_comments == []


@freeze_time("2026-01-01T12:00:00Z")
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


def _stacked_context(base_ref: str, default_branch: str) -> dict:
    return {
        "repo": "PostHog/posthog",
        "head_sha": "abc123",
        "base_sha": "def456",
        "pr": {
            "number": 11,
            "title": "feat: child of a stack",
            "state": "OPEN",
            "draft": False,
            "user": {"login": "author", "type": "User"},
            "base": {"ref": base_ref, "sha": "def456", "repo": {"default_branch": default_branch}},
        },
    }


@pytest.mark.parametrize(
    "base_ref, default_branch, expect_stacked",
    [
        pytest.param("master", "master", False, id="trunk-pr"),
        pytest.param("feat/parent", "master", True, id="stacked-on-a-parent-branch"),
        pytest.param("main", "main", False, id="trunk-named-main"),
    ],
)
def test_stacked_detection_follows_the_repo_default_branch(
    monkeypatch, base_ref: str, default_branch: str, expect_stacked: bool
) -> None:
    # The hosted runtime reviews repos whose trunk is "main"; a hardcoded "master" would tag every
    # PR there as stacked and mis-brief the reviewer.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])

    pr = review_local._build_pr_data(_stacked_context(base_ref, default_branch))

    assert pr.stacked is expect_stacked


def test_hosted_stacked_review_never_creates_a_worktree(monkeypatch) -> None:
    # The sandbox clones and checks out the PR head before the engine runs, so parent-PR symbols
    # already resolve. Reviving the Action's stacked-PR worktree here would be a wasted full-tree
    # checkout per stacked review, plus its symlink-rejection failure mode.
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    real_run = review_pr.subprocess.run

    def guarded_run(cmd, *args, **kwargs):
        assert "worktree" not in cmd, f"hosted review must not create a worktree: {cmd}"
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(review_pr.subprocess, "run", guarded_run)
    seen: dict = {}

    def fake_review(self, pr, classification, gate_context, diff_path=None):
        seen["explore_root"] = self.explore_root
        seen["stacked"] = pr.stacked
        return {"verdict": "APPROVE", "reasoning": "ok", "risk": "low", "issues": []}

    monkeypatch.setattr(review_pr.Reviewer, "review", fake_review)

    result = review_local.run(_stacked_context("feat/parent", "master"))

    assert result["final_verdict"] == "APPROVED"
    assert seen["stacked"] is True
    assert seen["explore_root"] == review_pr.REPO_ROOT
