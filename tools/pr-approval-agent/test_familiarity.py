"""Tests for the author-familiarity signal and its policy wiring."""

import os
import sys
import json
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock

import yaml

# reviewer.py (imported for the ratchet test) is a uv-script; stub its SDK dep.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import gates  # noqa: E402
import reviewer  # noqa: E402
import familiarity  # noqa: E402
from familiarity import AuthorFamiliarity, compute_familiarity  # noqa: E402
from github import PRData  # noqa: E402
from policy import (  # noqa: E402
    FamiliarityModerate,
    FamiliarityPolicy,
    FamiliarityStrong,
    PolicyError,
    default_policy_path,
    load_policy,
)

_LOCKFILE_NAMES = gates._ALL_LOCKFILE_NAMES
_OWNERSHIP_FORMATS = gates.OWNERSHIP_FORMAT_LOCATORS
_THRESHOLDS = FamiliarityPolicy(
    strong=FamiliarityStrong(min_blame_overlap_pct=50),
    moderate=FamiliarityModerate(min_prior_prs=3, max_days_since_touch=180),
)


# ── Throwaway git repo helpers (real git; gh is the only mocked boundary) ──


def _git(repo: Path, *args: str, author: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    if author:
        env["GIT_AUTHOR_NAME"] = author
        env["GIT_AUTHOR_EMAIL"] = f"{author}@example.com"
        env["GIT_COMMITTER_NAME"] = author
        env["GIT_COMMITTER_EMAIL"] = f"{author}@example.com"
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Base")
    _git(repo, "config", "user.email", "base@example.com")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, relpath: str, content: str, subject: str, author: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", relpath)
    _git(repo, "commit", "-q", "-m", subject, author=author)


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _patch_gh(monkeypatch: pytest.MonkeyPatch, *, pr_numbers: set[int] | None, returncode: int = 0) -> None:
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh":
            payload = json.dumps([{"number": n, "mergedAt": "2026-01-01T00:00:00Z"} for n in (pr_numbers or set())])
            return subprocess.CompletedProcess(cmd, returncode, stdout=payload if returncode == 0 else "", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(familiarity.subprocess, "run", fake_run)


def _numbered_lines(prefix: str, count: int) -> str:
    return "\n".join(f"{prefix} {i}" for i in range(1, count + 1)) + "\n"


# ── compute_familiarity end-to-end ───────────────────────────────


def test_strong_band_from_blame_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    original = _numbered_lines("line", 10)
    _commit(repo, "src/foo.py", original, "feat: add foo (#1)", "authora")
    base_sha = _head(repo)

    modified = original
    for n in (3, 6, 7, 8, 9):
        modified = modified.replace(f"line {n}\n", f"line {n} changed\n")
    (repo / "src/foo.py").write_text(modified)
    diff_path = tmp_path / "pr.diff"
    diff_path.write_text(_git(repo, "diff").stdout)

    _patch_gh(monkeypatch, pr_numbers={1})
    fam = compute_familiarity(
        author_login="authora",
        diff_path=diff_path,
        base_sha=base_sha,
        head_sha="HEAD",
        repo="PostHog/posthog",
        repo_root=repo,
        thresholds=_THRESHOLDS,
    )

    assert fam is not None
    assert fam.band == "STRONG"
    assert fam.modified_lines_total == 5
    assert fam.modified_lines_owned == 5
    assert fam.blame_overlap_pct == 100.0
    assert fam.capped is False


def test_none_band_for_author_without_matching_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    original = _numbered_lines("line", 6)
    _commit(repo, "src/foo.py", original, "feat: add foo (#1)", "authora")
    base_sha = _head(repo)
    (repo / "src/foo.py").write_text(original.replace("line 2\n", "line 2 changed\n"))
    diff_path = tmp_path / "pr.diff"
    diff_path.write_text(_git(repo, "diff").stdout)

    # A stranger with no merged PRs - gh returns an empty list, not a failure.
    _patch_gh(monkeypatch, pr_numbers=set())
    fam = compute_familiarity(
        author_login="stranger",
        diff_path=diff_path,
        base_sha=base_sha,
        head_sha="HEAD",
        repo="PostHog/posthog",
        repo_root=repo,
        thresholds=_THRESHOLDS,
    )

    assert fam is not None
    assert fam.band == "NONE"
    assert fam.blame_overlap_pct == 0.0
    assert fam.prior_prs_in_paths == 0


def test_gh_failure_yields_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "src/foo.py", _numbered_lines("line", 4), "feat: add foo (#1)", "authora")
    base_sha = _head(repo)
    diff_path = tmp_path / "pr.diff"
    diff_path.write_text(_git(repo, "diff").stdout)

    _patch_gh(monkeypatch, pr_numbers=None, returncode=1)
    fam = compute_familiarity(
        author_login="authora",
        diff_path=diff_path,
        base_sha=base_sha,
        head_sha="HEAD",
        repo="PostHog/posthog",
        repo_root=repo,
        thresholds=_THRESHOLDS,
    )

    assert fam is None


def test_capped_flag_set_when_file_exceeds_line_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    big = _numbered_lines("b", 2200)
    _commit(repo, "src/big.py", big, "feat: big (#1)", "authora")
    base_sha = _head(repo)
    (repo / "src/big.py").write_text(_numbered_lines("bx", 2200))
    diff_path = tmp_path / "pr.diff"
    diff_path.write_text(_git(repo, "diff").stdout)

    _patch_gh(monkeypatch, pr_numbers={1})
    fam = compute_familiarity(
        author_login="authora",
        diff_path=diff_path,
        base_sha=base_sha,
        head_sha="HEAD",
        repo="PostHog/posthog",
        repo_root=repo,
        thresholds=_THRESHOLDS,
    )

    assert fam is not None
    assert fam.capped is True
    # The oversize file is skipped, so nothing was blamed.
    assert fam.modified_lines_total == 0


def test_files_previously_modified_counts_renamed_file_by_old_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    original = _numbered_lines("line", 6)
    _commit(repo, "src/foo.py", original, "feat: add foo (#1)", "authora")
    base_sha = _head(repo)

    _git(repo, "mv", "src/foo.py", "src/bar.py")
    (repo / "src/bar.py").write_text(original.replace("line 2\n", "line 2 changed\n"))
    diff_path = tmp_path / "pr.diff"
    diff_path.write_text(_git(repo, "diff", base_sha).stdout)

    _patch_gh(monkeypatch, pr_numbers={1})
    fam = compute_familiarity(
        author_login="authora",
        diff_path=diff_path,
        base_sha=base_sha,
        head_sha="HEAD",
        repo="PostHog/posthog",
        repo_root=repo,
        thresholds=_THRESHOLDS,
    )

    assert fam is not None
    # git log -- src/bar.py alone would miss authora's PR #1, recorded under src/foo.py.
    assert fam.files_prev_count == 1
    assert fam.files_total == 1


# ── Band thresholds (pure) ───────────────────────────────────────


@pytest.mark.parametrize(
    "blame, prior, days, expected",
    [
        (60, 0, None, "STRONG"),  # blame overlap alone, nothing else
        (50, 0, None, "STRONG"),  # boundary inclusive
        (49, 3, 90, "MODERATE"),  # just under blame threshold, moderate holds
        (10, 2, 10, "NONE"),  # moderate fails on prior_prs
        (10, 3, None, "NONE"),  # no last touch → moderate cannot hold
        (10, 3, 181, "NONE"),  # moderate fails on days
    ],
)
def test_band_thresholds(blame: float, prior: int, days: int | None, expected: str) -> None:
    assert familiarity._band(blame, prior, days, _THRESHOLDS) == expected


# ── Policy loader wiring ─────────────────────────────────────────


def _valid_policy_dict() -> dict:
    return yaml.safe_load(default_policy_path().read_text())


def test_familiarity_section_loaded() -> None:
    policy = load_policy(lockfile_names=_LOCKFILE_NAMES, ownership_formats=_OWNERSHIP_FORMATS)
    assert policy.familiarity.strong.min_blame_overlap_pct == 70
    assert policy.familiarity.moderate.min_prior_prs == 5
    assert policy.familiarity.moderate.max_days_since_touch == 180


def _drop_familiarity(d: dict) -> None:
    del d["familiarity"]


def _unknown_familiarity_key(d: dict) -> None:
    d["familiarity"]["strong"]["bogus"] = 1


def _missing_familiarity_subkey(d: dict) -> None:
    del d["familiarity"]["strong"]["min_blame_overlap_pct"]


def _negative_prior_prs(d: dict) -> None:
    d["familiarity"]["moderate"]["min_prior_prs"] = -1


def _blame_pct_over_100(d: dict) -> None:
    d["familiarity"]["strong"]["min_blame_overlap_pct"] = 150


@pytest.mark.parametrize(
    "mutate",
    [
        _drop_familiarity,
        _unknown_familiarity_key,
        _missing_familiarity_subkey,
        _negative_prior_prs,
        _blame_pct_over_100,
    ],
)
def test_malformed_familiarity_hard_fails(tmp_path: Path, mutate) -> None:
    data = _valid_policy_dict()
    mutate(data)
    bad = tmp_path / "policy.yml"
    bad.write_text(yaml.safe_dump(data))
    with pytest.raises(PolicyError):
        load_policy(bad, lockfile_names=_LOCKFILE_NAMES, ownership_formats=_OWNERSHIP_FORMATS)


# ── Ratchet: absent familiarity leaves the prompt byte-identical ──


def _prompt_fixture() -> tuple[PRData, dict, dict]:
    pr = PRData(
        number=7,
        repo="PostHog/posthog",
        title="fix: tidy helper",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
        base_sha="base",
        head_sha="head",
        files=[{"filename": "src/foo.py", "additions": 3, "deletions": 1, "status": "M"}],
        reviews=[],
        review_comments=[],
        check_runs=[],
    )
    cl = {
        "tier": "T1-agent",
        "t1_subclass": "T1b-small",
        "breadth": "single-area",
        "commit_type": "fix",
        "ownership": {},
        "title_scrutiny_flags": [],
        "dep_manifests_without_lockfile": [],
        "folder_policy_prose": None,
        "familiarity": None,
    }
    gate_context = {"gate_verdict": "PENDING", "gates": [{"gate": "size", "passed": True, "message": "ok"}]}
    return pr, cl, gate_context


def test_absent_familiarity_keeps_prompt_identical() -> None:
    rev = reviewer.Reviewer(Path("/tmp"))
    pr, cl_with_none, gate_context = _prompt_fixture()
    cl_without = {k: v for k, v in cl_with_none.items() if k != "familiarity"}

    with_none = rev._build_review_prompt(pr, cl_with_none, gate_context, Path("/x.diff"))
    without_key = rev._build_review_prompt(pr, cl_without, gate_context, Path("/x.diff"))

    assert with_none == without_key
    assert "Author familiarity" not in with_none


def _fam(band: str, top_authors: tuple[str, ...]) -> AuthorFamiliarity:
    return AuthorFamiliarity(
        band=band,
        blame_overlap_pct=0.0,
        modified_lines_owned=0,
        modified_lines_total=40,
        prior_prs_in_paths=0,
        days_since_last_touch=None,
        files_prev_count=0,
        files_total=3,
        capped=False,
        top_prior_authors=top_authors,
    )


def test_none_band_withholds_negative_facts_but_keeps_routing_hint() -> None:
    rev = reviewer.Reviewer(Path("/tmp"))
    pr, cl, gate_context = _prompt_fixture()

    cl["familiarity"] = _fam("NONE", ("Alice Smith", "Bob Jones"))
    prompt = rev._build_review_prompt(pr, cl, gate_context, Path("/x.diff"))
    assert "Author familiarity" not in prompt
    assert "Most familiar with the modified lines" in prompt

    cl["familiarity"] = _fam("NONE", ())
    prompt_no_hint = rev._build_review_prompt(pr, cl, gate_context, Path("/x.diff"))
    assert "familiar" not in prompt_no_hint


@pytest.mark.parametrize("band", ["NONE", "MODERATE"])
def test_top_prior_authors_are_sanitized_in_prompt(band: str) -> None:
    # top_prior_authors comes from git blame - a contributor-controlled Git
    # author name - rendered into the TRUSTED section of the prompt; a
    # dropped sanitizer wrapper would let a bidi-override name through raw.
    rev = reviewer.Reviewer(Path("/tmp"))
    pr, cl, gate_context = _prompt_fixture()

    malicious_name = "Eve\u202e" + "x" * 100
    cl["familiarity"] = _fam(band, (malicious_name,))
    prompt = rev._build_review_prompt(pr, cl, gate_context, Path("/x.diff"))

    assert "\u202e" not in prompt
    assert malicious_name not in prompt
