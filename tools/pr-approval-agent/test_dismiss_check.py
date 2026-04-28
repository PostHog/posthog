"""Tests for the Stamphog dismiss-decision logic."""

import os
import subprocess
from pathlib import Path

import pytest

import dismiss_check
from dismiss_check import decide, evaluate_delta
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
        # Snapshots
        ("foo.snap", True),
        ("foo/__snapshots__/bar.snap", True),
        # Docs
        ("README.md", True),
        ("CHANGELOG.md", True),
        ("docs/foo.md", True),
        ("foo.mdx", True),
        # Lockfiles
        ("package-lock.json", True),
        ("pnpm-lock.yaml", True),
        ("frontend/yarn.lock", True),
        ("uv.lock", True),
        ("Cargo.lock", True),
        # Generated
        ("frontend/src/generated/core/api.ts", True),
        ("products/foo/frontend/generated/api.ts", True),
        ("frontend/src/queries/schema/general.ts", True),
        ("foo.gen.ts", True),
        ("foo.generated.py", True),
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


# ── evaluate_delta scenarios ─────────────────────────────────────


def test_test_only_delta_retains(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "tests/test_foo.py", "def test_foo(): pass")
    _commit(repo, "test only")
    result = evaluate_delta(base, _head(repo), repo)
    assert result["action"] == "retain"
    assert result["reason"] == "trivial_paths"


def test_lockfile_only_delta_retains(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "package-lock.json", "{}")
    _commit(repo, "lock")
    result = evaluate_delta(base, _head(repo), repo)
    assert result["action"] == "retain"
    assert result["reason"] == "trivial_paths"


def test_workflow_change_dismisses(repo: Path) -> None:
    base = _head(repo)
    _write(repo, ".github/workflows/foo.yml", "name: x")
    _commit(repo, "workflow")
    result = evaluate_delta(base, _head(repo), repo)
    assert result["action"] == "dismiss"
    assert result["reason"] == "non_trivial_delta"


def test_prod_file_dismisses(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "frontend/src/foo.ts", "export const x = 1")
    _commit(repo, "prod")
    result = evaluate_delta(base, _head(repo), repo)
    assert result["action"] == "dismiss"
    assert result["reason"] == "non_trivial_delta"


def test_generated_file_only_retains(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "frontend/src/generated/core/api.ts", "export const x = 1")
    _commit(repo, "regen")
    result = evaluate_delta(base, _head(repo), repo)
    assert result["action"] == "retain"
    assert result["reason"] == "trivial_paths"


def test_mixed_test_plus_prod_dismisses(repo: Path) -> None:
    base = _head(repo)
    _write(repo, "frontend/src/foo.test.ts", "test('x', () => {})")
    _write(repo, "frontend/src/foo.ts", "export const x = 1")
    _commit(repo, "mixed")
    result = evaluate_delta(base, _head(repo), repo)
    assert result["action"] == "dismiss"
    assert result["reason"] == "non_trivial_delta"


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

    result = evaluate_delta(feat_sha, _head(repo), repo, base_ref="master")
    assert result["action"] == "retain"
    assert result["reason"] == "merge_only"


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

    result = evaluate_delta(feat_sha, _head(repo), repo, base_ref="master")
    assert result["action"] == "dismiss"
    assert result["reason"] == "non_trivial_delta"


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

    result = evaluate_delta(feat_sha, _head(repo), repo, base_ref="master")
    assert result["action"] == "retain"
    assert result["reason"] == "mixed_trivial"


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

    result = evaluate_delta(feat_sha, _head(repo), repo, base_ref="master")
    assert result["action"] == "dismiss"
    assert result["reason"] == "non_trivial_delta"


def test_non_linear_history_dismisses(repo: Path) -> None:
    _git("checkout", "-b", "feat", cwd=repo)
    _write(repo, "a.ts", "a")
    feat_sha = _commit(repo, "feat a")

    # Simulate force-push: reset and create a divergent commit
    _git("reset", "--hard", "HEAD~1", cwd=repo)
    _write(repo, "a.ts", "different a")
    _commit(repo, "rebased a")

    result = evaluate_delta(feat_sha, _head(repo), repo)
    assert result["action"] == "dismiss"
    assert result["reason"] == "non_linear_history"


def test_empty_delta_retains(repo: Path) -> None:
    head = _head(repo)
    result = evaluate_delta(head, head, repo)
    assert result["action"] == "retain"
    assert result["reason"] == "empty_delta"


# ── edge cases ───────────────────────────────────────────────────


def test_empty_commit_retains(repo: Path) -> None:
    base = _head(repo)
    _git("commit", "--allow-empty", "-m", "empty", cwd=repo)
    result = evaluate_delta(base, _head(repo), repo, base_ref="master")
    assert result["action"] == "retain"
    assert result["reason"] == "trivial_paths"


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

    result = evaluate_delta(feat_sha, _head(repo), repo, base_ref="master")
    assert result["action"] == "dismiss"
    assert result["reason"] == "non_trivial_delta"


# ── decide() with mocked GitHub API ──────────────────────────────


def test_decide_no_prior_approval(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    monkeypatch.setattr(dismiss_check, "find_last_approved_sha", lambda *_: None)
    result = decide("PostHog/posthog", 1, _head(repo), repo)
    assert result["action"] == "dismiss"
    assert result["reason"] == "no_prior_approval"
    assert result["last_approved_sha"] is None


def test_decide_returns_last_approved_sha(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    base = _head(repo)
    _write(repo, "tests/test_foo.py", "def test_foo(): pass")
    _commit(repo, "test")

    monkeypatch.setattr(dismiss_check, "find_last_approved_sha", lambda *_: base)
    result = decide("PostHog/posthog", 1, _head(repo), repo)
    assert result["action"] == "retain"
    assert result["last_approved_sha"] == base
