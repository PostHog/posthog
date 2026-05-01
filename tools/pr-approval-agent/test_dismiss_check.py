"""Tests for the Stamphog dismiss-decision logic."""

import os
import subprocess
from pathlib import Path

import pytest

import dismiss_check
from dismiss_check import Decision, decide, evaluate_delta, select_last_bot_approval
from gates import is_trivial_at_dismiss_time

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
    )


def _write(repo: Path, path: str, content: str = "x") -> None:
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _commit(repo: Path, message: str) -> str:
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", message, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def _head(repo: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def _assert_decision(d: Decision, *, dismiss: bool, review: bool, reason: str) -> None:
    assert d.dismiss_approval is dismiss
    assert d.run_review is review
    assert d.reason == reason


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Empty repo with one initial commit on master."""
    _git("init", "--initial-branch=master", cwd=tmp_path)
    _write(tmp_path, "README.md", "init")
    _commit(tmp_path, "init")
    return tmp_path


# ── is_trivial_at_dismiss_time unit tests ────────────────────────


@pytest.mark.parametrize(
    "path,expected",
    [
        # Tests
        ("frontend/src/foo.test.ts", True),
        ("frontend/src/foo.test.tsx", True),
        ("frontend/src/foo.spec.ts", True),
        ("posthog/test_views.py", True),
        ("posthog/api/test/foo.py", True),
        ("tests/test_foo.py", True),
        ("foo/__tests__/bar.ts", True),
        ("conftest.py", True),
        ("posthog/conftest.py", True),
        ("internal_test.go", True),
        ("posthog/fixtures/foo.json", True),
        # Snapshots — only the canonical __snapshots__/ directory; bare
        # .snap suffix anywhere is no longer trusted.
        ("foo/__snapshots__/bar.snap", True),
        ("__snapshots__/bar.snap", True),
        ("scripts/deploy.snap", False),
        ("foo.snap", False),
        # Docs
        ("README.md", True),
        ("CHANGELOG.md", True),
        ("docs/foo.md", True),
        ("foo.mdx", True),
        # Lockfiles (matched case-insensitively)
        ("package-lock.json", True),
        ("pnpm-lock.yaml", True),
        ("frontend/yarn.lock", True),
        ("uv.lock", True),
        ("Cargo.lock", True),
        ("CARGO.LOCK", True),
        ("Gemfile.lock", True),
        ("Pipfile.LOCK", True),
        # Generated — frontend TS / JS / JSON / md / snap / type-stubs only.
        # Backend executable code (.py, .go) under generated/ is NOT trivial
        # because at dismiss time the path is the only signal.
        ("frontend/src/generated/core/api.ts", True),
        ("products/foo/frontend/generated/api.ts", True),
        ("nodejs/src/generated/foo.ts", True),
        ("services/mcp/src/generated/foo.ts", True),
        ("frontend/src/queries/schema/general.ts", True),
        ("foo.gen.ts", True),
        ("foo.generated.ts", True),
        ("services/mcp/src/ui-apps/generated/foo.txt", True),
        # Backend code under generated/ — must dismiss
        ("posthog/generated/evil.py", False),
        ("posthog/personhog_client/proto/generated/foo.py", False),
        ("services/foo/generated/handler.go", False),
        ("foo.gen.py", False),
        ("foo.generated.py", False),
        ("foo.gen.go", False),
        ("foo.generated.go", False),
        # NOT allowed
        (".github/workflows/foo.yml", False),
        (".github/CODEOWNERS", False),
        ("Dockerfile", False),
        ("scripts/deploy.sh", False),
        ("Makefile", False),
        ("pyproject.toml", False),
        ("tsconfig.json", False),
        ("frontend/src/foo.ts", False),
        ("posthog/api/foo.py", False),
        ("requirements.txt", False),
        ("package.json", False),
    ],
)
def test_is_trivial_at_dismiss_time(path: str, expected: bool) -> None:
    assert is_trivial_at_dismiss_time(path) is expected


# ── _is_ancestor unit tests ──────────────────────────────────────


def test_is_ancestor_returns_true_when_ancestor(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "a.ts", "a")
    head = _commit(repo, "feat a")
    assert dismiss_check._is_ancestor(base, head, repo) is True


def test_is_ancestor_returns_false_when_not_ancestor(repo: Path) -> None:
    _write(repo, "a.ts", "a")
    a = _commit(repo, "feat a")
    _git("reset", "--hard", "HEAD~1", cwd=repo)
    _write(repo, "b.ts", "b")
    b = _commit(repo, "feat b")
    assert dismiss_check._is_ancestor(a, b, repo) is False


def test_is_ancestor_returns_false_on_git_error(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bogus = "0" * 40
    assert dismiss_check._is_ancestor(bogus, _head(repo), repo) is False
    assert "_is_ancestor git error" in capsys.readouterr().err


# ── evaluate_delta scenarios ─────────────────────────────────────


def test_test_only_delta_retains(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "tests/test_foo.py", "def test_foo(): pass")
    _commit(repo, "test only")
    _assert_decision(evaluate_delta(base, _head(repo), repo), dismiss=False, review=False, reason="trivial_paths")


def test_lockfile_only_delta_retains(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "package-lock.json", "{}")
    _commit(repo, "lock")
    _assert_decision(evaluate_delta(base, _head(repo), repo), dismiss=False, review=False, reason="trivial_paths")


def test_workflow_change_dismisses(repo: Path) -> None:
    base = _head(repo)
    _write(repo, ".github/workflows/foo.yml", "name: x")
    _commit(repo, "workflow")
    _assert_decision(evaluate_delta(base, _head(repo), repo), dismiss=True, review=True, reason="non_trivial_delta")


def test_prod_file_dismisses(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "frontend/src/foo.ts", "export const x = 1")
    _commit(repo, "prod")
    _assert_decision(evaluate_delta(base, _head(repo), repo), dismiss=True, review=True, reason="non_trivial_delta")


def test_generated_file_only_retains(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "frontend/src/generated/core/api.ts", "export const x = 1")
    _commit(repo, "regen")
    _assert_decision(evaluate_delta(base, _head(repo), repo), dismiss=False, review=False, reason="trivial_paths")


def test_mixed_test_plus_prod_dismisses(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "frontend/src/foo.test.ts", "test('x', () => {})")
    _write(repo, "frontend/src/foo.ts", "export const x = 1")
    _commit(repo, "mixed")
    _assert_decision(evaluate_delta(base, _head(repo), repo), dismiss=True, review=True, reason="non_trivial_delta")


def test_clean_merge_from_master_retains(repo: Path) -> None:
    # Branch off and commit on feat
    _git("checkout", "-b", "feat", cwd=repo)
    _write(repo, "feat.ts", "feat")
    feat_sha = _commit(repo, "feat")

    # Advance master with a non-overlapping change
    _git("checkout", "master", cwd=repo)
    _write(repo, "main.ts", "main")
    _commit(repo, "main change")

    # Merge master into feat (no conflicts)
    _git("checkout", "feat", cwd=repo)
    _git("merge", "--no-ff", "master", "-m", "merge master", cwd=repo)

    _assert_decision(
        evaluate_delta(feat_sha, _head(repo), repo, base_ref="master"),
        dismiss=False,
        review=False,
        reason="merge_only",
    )


def test_merge_with_conflict_resolution_dismisses(repo: Path) -> None:
    # Both branches modify the same file → manual resolution
    _git("checkout", "-b", "feat", cwd=repo)
    _write(repo, "shared.ts", "feat version")
    feat_sha = _commit(repo, "feat shared")

    _git("checkout", "master", cwd=repo)
    _write(repo, "shared.ts", "main version")
    _commit(repo, "main shared")

    _git("checkout", "feat", cwd=repo)
    # Merge will conflict; resolve manually
    _git("merge", "--no-ff", "--no-commit", "master", cwd=repo, check=False)
    _write(repo, "shared.ts", "manually resolved")
    _git("add", "shared.ts", cwd=repo)
    _git("commit", "--no-edit", cwd=repo)

    _assert_decision(
        evaluate_delta(feat_sha, _head(repo), repo, base_ref="master"),
        dismiss=True,
        review=True,
        reason="non_trivial_delta",
    )


def test_clean_merge_plus_test_commit_retains(repo: Path) -> None:
    _git("checkout", "-b", "feat", cwd=repo)
    _write(repo, "feat.ts", "feat")
    feat_sha = _commit(repo, "feat")

    _git("checkout", "master", cwd=repo)
    _write(repo, "main.ts", "main")
    _commit(repo, "main change")

    _git("checkout", "feat", cwd=repo)
    _git("merge", "--no-ff", "master", "-m", "merge master", cwd=repo)
    # Then add a test
    _write(repo, "tests/test_feat.py", "def test_feat(): pass")
    _commit(repo, "tests")

    _assert_decision(
        evaluate_delta(feat_sha, _head(repo), repo, base_ref="master"),
        dismiss=False,
        review=False,
        reason="mixed_trivial",
    )


def test_clean_merge_plus_prod_commit_dismisses(repo: Path) -> None:
    _git("checkout", "-b", "feat", cwd=repo)
    _write(repo, "feat.ts", "feat")
    feat_sha = _commit(repo, "feat")

    _git("checkout", "master", cwd=repo)
    _write(repo, "main.ts", "main")
    _commit(repo, "main change")

    _git("checkout", "feat", cwd=repo)
    _git("merge", "--no-ff", "master", "-m", "merge master", cwd=repo)
    _write(repo, "feat.ts", "feat updated")
    _commit(repo, "prod tweak")

    _assert_decision(
        evaluate_delta(feat_sha, _head(repo), repo, base_ref="master"),
        dismiss=True,
        review=True,
        reason="non_trivial_delta",
    )


def test_non_linear_history_dismisses(repo: Path) -> None:
    _git("checkout", "-b", "feat", cwd=repo)
    _write(repo, "a.ts", "a")
    feat_sha = _commit(repo, "feat a")

    # Simulate force-push: reset and create a divergent commit
    _git("reset", "--hard", "HEAD~1", cwd=repo)
    _write(repo, "a.ts", "different a")
    _commit(repo, "rebased a")

    _assert_decision(
        evaluate_delta(feat_sha, _head(repo), repo), dismiss=True, review=True, reason="non_linear_history"
    )


def test_empty_delta_retains(repo: Path) -> None:
    head = _head(repo)
    _assert_decision(evaluate_delta(head, head, repo), dismiss=False, review=False, reason="empty_delta")


# ── edge cases ───────────────────────────────────────────────────


def test_empty_commit_retains(repo: Path) -> None:
    base = _head(repo)
    _git("commit", "--allow-empty", "-m", "empty", cwd=repo)
    _assert_decision(
        evaluate_delta(base, _head(repo), repo, base_ref="master"),
        dismiss=False,
        review=False,
        reason="trivial_paths",
    )


def test_merge_from_non_base_branch_dismisses(repo: Path) -> None:
    # PR branch
    _git("checkout", "-b", "feat", cwd=repo)
    _write(repo, "feat.ts", "feat")
    feat_sha = _commit(repo, "feat")

    # Side branch off master with a prod commit, never landed on master
    _git("checkout", "-b", "side", "master", cwd=repo)
    _write(repo, "side.ts", "side")
    _commit(repo, "side prod change")

    # Merge side into feat (clean merge, but side isn't in master history)
    _git("checkout", "feat", cwd=repo)
    _git("merge", "--no-ff", "side", "-m", "merge side", cwd=repo)

    _assert_decision(
        evaluate_delta(feat_sha, _head(repo), repo, base_ref="master"),
        dismiss=True,
        review=True,
        reason="non_trivial_delta",
    )


# ── decide() with mocked GitHub API ──────────────────────────────


def test_decide_no_prior_approval(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    # No prior bot approval → no_op. Re-review here would burn LLM credits
    # for a state we didn't create (a human dismissed the approval out-of-
    # band) and the label-add path is the canonical re-review trigger.
    monkeypatch.setattr(dismiss_check, "find_last_approved_sha", lambda *_: None)
    result = decide("PostHog/posthog", 1, _head(repo), repo)
    _assert_decision(result, dismiss=False, review=False, reason="no_prior_approval")
    assert result.last_approved_sha is None


def test_decide_returns_last_approved_sha(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    base = _head(repo)
    _write(repo, "tests/test_foo.py", "def test_foo(): pass")
    _commit(repo, "test")

    monkeypatch.setattr(dismiss_check, "find_last_approved_sha", lambda *_: base)
    result = decide("PostHog/posthog", 1, _head(repo), repo)
    _assert_decision(result, dismiss=False, review=False, reason="trivial_paths")
    assert result.last_approved_sha == base


def test_decide_dismiss_path_includes_last_approved_sha(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    base = _head(repo)
    _write(repo, "frontend/src/foo.ts", "export const x = 1")
    _commit(repo, "prod")

    monkeypatch.setattr(dismiss_check, "find_last_approved_sha", lambda *_: base)
    result = decide("PostHog/posthog", 1, _head(repo), repo)
    _assert_decision(result, dismiss=True, review=True, reason="non_trivial_delta")
    assert result.last_approved_sha == base


# ── select_last_bot_approval (filter + sort) ─────────────────────


def _review(login: str, state: str, commit_id: str, submitted_at: str) -> dict:
    return {
        "user": {"login": login},
        "state": state,
        "commit_id": commit_id,
        "submitted_at": submitted_at,
    }


def test_select_last_bot_approval_empty_list() -> None:
    assert select_last_bot_approval([]) is None


def test_select_last_bot_approval_no_bot_reviews() -> None:
    reviews = [_review("alice", "APPROVED", "sha1", "2026-01-01T00:00:00Z")]
    assert select_last_bot_approval(reviews) is None


def test_select_last_bot_approval_no_approved_state() -> None:
    reviews = [
        _review("github-actions[bot]", "COMMENTED", "sha1", "2026-01-01T00:00:00Z"),
        _review("github-actions[bot]", "CHANGES_REQUESTED", "sha2", "2026-01-02T00:00:00Z"),
    ]
    assert select_last_bot_approval(reviews) is None


def test_select_last_bot_approval_picks_latest() -> None:
    reviews = [
        _review("github-actions[bot]", "APPROVED", "sha-old", "2026-01-01T00:00:00Z"),
        _review("github-actions[bot]", "APPROVED", "sha-new", "2026-02-01T00:00:00Z"),
        _review("github-actions[bot]", "APPROVED", "sha-mid", "2026-01-15T00:00:00Z"),
    ]
    assert select_last_bot_approval(reviews) == "sha-new"


def test_select_last_bot_approval_ignores_human_approvals() -> None:
    reviews = [
        _review("github-actions[bot]", "APPROVED", "sha-bot", "2026-01-01T00:00:00Z"),
        _review("alice", "APPROVED", "sha-human", "2026-02-01T00:00:00Z"),
    ]
    assert select_last_bot_approval(reviews) == "sha-bot"


def test_select_last_bot_approval_ignores_bot_non_approval_states() -> None:
    reviews = [
        _review("github-actions[bot]", "APPROVED", "sha-approved", "2026-01-01T00:00:00Z"),
        _review("github-actions[bot]", "CHANGES_REQUESTED", "sha-changes", "2026-02-01T00:00:00Z"),
    ]
    assert select_last_bot_approval(reviews) == "sha-approved"


# ── main() error path ────────────────────────────────────────────


def test_main_missing_env_emits_dismiss(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # REPO is the first env var read in main(); leaving it unset triggers KeyError.
    for key in ("REPO", "PR_NUMBER", "HEAD_SHA"):
        monkeypatch.delenv(key, raising=False)

    dismiss_check.main()
    out = capsys.readouterr().out.strip()

    import json as _json

    decision = _json.loads(out)
    assert decision["dismiss_approval"] is True
    assert decision["run_review"] is True
    assert decision["reason"].startswith("error:")
    assert decision["last_approved_sha"] is None
