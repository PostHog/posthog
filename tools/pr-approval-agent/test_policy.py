"""Tests for the declarative policy loader, resolver, and prompt recomposition."""

import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock

import yaml

# reviewer.py is a uv-script; stub its claude_agent_sdk dep like the sibling suites.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import gates  # noqa: E402
import policy  # noqa: E402
import reviewer  # noqa: E402
import review_pr  # noqa: E402
from familiarity import AuthorFamiliarity  # noqa: E402
from github import PRData  # noqa: E402
from policy import (  # noqa: E402
    EffectivePolicy,
    PolicyError,
    ScopeBudget,
    _sanitize_folder_prose,
    default_policy_path,
    load_policy,
    resolve,
)

_LOCKFILE_NAMES = gates._ALL_LOCKFILE_NAMES
_OWNERSHIP_FORMATS = gates.OWNERSHIP_FORMAT_LOCATORS

# ── Frozen pre-extraction constants (verbatim, captured before removal) ──
#
# Migration guards: these pin the extraction to the exact pre-extraction values
# so a YAML transcription slip (a mangled regex escape, a dropped entry) cannot
# pass silently. The first INTENTIONAL policy change must update the frozen copy
# here in the same PR - that is by design: machine-policy edits always touch two
# human-reviewed files. (The prose guidance file is deliberately NOT frozen -
# wording changes are governed by human review via the stamphog_policy deny.)

OLD_DENY_PATTERN_DEFS = {
    "auth": {
        "any": [
            "auth",
            "login",
            "signup",
            "oauth",
            "saml",
            "sso",
            "oidc",
            "credential",
            "password",
            "2fa",
            "mfa",
            "authentication",
            "authenticate",
            "authorize",
            "authorization",
            "two[_-]?factor",
        ],
        "titles": ["authenticated", "authorized"],
        "paths": ["session_auth", "session_token", "auth/session", "auth/token", "permission"],
    },
    "crypto_secrets": {
        "any": ["crypto", "encrypt", "decrypt", "vault"],
        "paths": [
            "secret",
            "api[_-]?key",
            "secret[_-]?key",
            "private[_-]?key",
            "signing[_-]?key",
            "certificate",
            "\\.env",
            "\\.pem",
        ],
    },
    "migrations": {"paths": ["migrations/", "schema_change"]},
    "infra_cicd": {
        "any": ["terraform", "kubernetes", "helm"],
        "paths": [
            "k8s",
            "dockerfile",
            "docker-compose",
            "\\.github/workflows",
            "\\.github/pr-deploy",
            "iam",
            "cloudflare",
            "cdn",
            "waf",
            "(?:^|/)bin/deploy",
            "deploy\\.sh",
        ],
    },
    "billing": {"any": ["billing", "payment", "stripe", "invoice", "pricing"]},
    "public_api": {"any": ["openapi", "api_schema", "swagger", "public_api"]},
    "deps_toolchain": {
        "paths": [
            "cargo\\.lock",
            "composer\\.lock",
            "gemfile\\.lock",
            "go\\.sum",
            "npm\\-shrinkwrap\\.json",
            "package\\-lock\\.json",
            "pipfile\\.lock",
            "pnpm\\-lock\\.yaml",
            "poetry\\.lock",
            "uv\\.lock",
            "yarn\\.lock",
            "requirements[-\\w]*\\.(txt|in)",
            "Makefile",
            "Dockerfile",
            "\\.tool-versions",
            "\\.nvmrc",
        ]
    },
}
OLD_ALLOW_ONLY_EXTENSIONS = {
    ".txt",
    ".yml",
    ".lock",
    ".yaml",
    ".toml",
    ".jpeg",
    ".ini",
    ".jpg",
    ".png",
    ".ico",
    ".cfg",
    ".csv",
    ".snap",
    ".webp",
    ".gif",
    ".mdx",
    ".rst",
    ".md",
    ".json",
    ".svg",
}
OLD_ALLOW_PATH_PATTERNS = [
    "docs/",
    "README",
    "CHANGELOG",
    "LICENSE",
    "CONTRIBUTING",
    ".github/CODEOWNERS",
    ".gitignore",
    ".editorconfig",
    "generated/",
    "__snapshots__/",
]
OLD_MAX_LINES = 500
OLD_MAX_FILES = 20
OLD_DISMISS_TEST_RE = "(?:^|/)(?:__tests__|tests?|fixtures)/|(?:^|/)test_[^/]+\\.py$|_test\\.(py|go)$|\\.test\\.(ts|tsx|js|jsx)$|\\.spec\\.(ts|tsx|js|jsx)$|(?:^|/)conftest\\.py$"
OLD_DISMISS_GENERATED_RE = "(?:^|/)generated/.*\\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$|\\.gen\\.(ts|tsx|js|jsx)$|\\.generated\\.(ts|tsx|js|jsx)$|^frontend/src/queries/schema/"

# ── 1. Equality snapshot: loaded policy matches pre-extraction literals ──


def test_deny_defs_equal_pre_extraction_excluding_stamphog_policy() -> None:
    live = {k: v for k, v in gates._DENY_PATTERN_DEFS.items() if k != "stamphog_policy"}
    assert live == OLD_DENY_PATTERN_DEFS


def test_allow_size_and_dismiss_equal_pre_extraction() -> None:
    assert set(gates.ALLOW_ONLY_EXTENSIONS) == OLD_ALLOW_ONLY_EXTENSIONS
    assert list(gates.ALLOW_PATH_PATTERNS) == OLD_ALLOW_PATH_PATTERNS
    assert gates.MAX_LINES == OLD_MAX_LINES
    assert gates.MAX_FILES == OLD_MAX_FILES
    assert gates._DISMISS_TIME_TEST_RE.pattern == OLD_DISMISS_TEST_RE
    assert gates._DISMISS_TIME_GENERATED_RE.pattern == OLD_DISMISS_GENERATED_RE


@pytest.mark.parametrize(
    "lines, files, breadth, expected",
    [
        (20, 3, "single-area", "T1a-trivial"),
        (20, 3, "two-areas", "T1b-small"),
        (100, 5, "two-areas", "T1b-small"),
        (300, 15, "two-areas", "T1c-medium"),
        (301, 15, "two-areas", "T1d-complex"),
        (50, 4, "cross-cutting", "T1d-complex"),
    ],
)
def test_tier_thresholds_unchanged(lines: int, files: int, breadth: str, expected: str) -> None:
    assert gates.t1_risk_subclass(lines_total=lines, files_changed=files, breadth=breadth) == expected


# ── 2. Malformed global policy hard-fails at load ──


def _valid_policy_dict() -> dict:
    return yaml.safe_load(default_policy_path().read_text())


def _unknown_top_level_key(d: dict) -> None:
    d["bogus"] = 1


def _empty_pattern_list(d: dict) -> None:
    d["deny"]["auth"]["match"]["any"] = []


def _invalid_regex(d: dict) -> None:
    d["deny"]["auth"]["match"]["paths"] = ["("]


def _drop_self_governance(d: dict) -> None:
    del d["deny"]["stamphog_policy"]


def _out_of_contract_delegation(d: dict) -> None:
    d["overrides"]["deny"] = {"ceiling": 1}


def _rename_deps_toolchain(d: dict) -> None:
    d["deny"]["dependencies_toolchain"] = d["deny"].pop("deps_toolchain")


def _ownership_unknown_format(d: dict) -> None:
    d["ownership"]["sources"][0]["format"] = "svn-blame"


def _ownership_both_locators(d: dict) -> None:
    d["ownership"]["sources"][0]["glob"] = "products/*/product.yaml"


def _ownership_no_locator(d: dict) -> None:
    del d["ownership"]["sources"][0]["path"]


def _ownership_empty_sources(d: dict) -> None:
    d["ownership"]["sources"] = []


def _ownership_path_escapes_repo(d: dict) -> None:
    d["ownership"]["sources"][0]["path"] = "../x"


def _ownership_wrong_locator_for_format(d: dict) -> None:
    d["ownership"]["sources"][1] = {"format": "ph-product", "path": "products/foo/product.yaml"}


@pytest.mark.parametrize(
    "mutate",
    [
        _unknown_top_level_key,
        _empty_pattern_list,
        _invalid_regex,
        _drop_self_governance,
        _out_of_contract_delegation,
        _rename_deps_toolchain,
        _ownership_unknown_format,
        _ownership_both_locators,
        _ownership_no_locator,
        _ownership_empty_sources,
        _ownership_path_escapes_repo,
        _ownership_wrong_locator_for_format,
    ],
)
def test_malformed_policy_hard_fails(tmp_path: Path, mutate) -> None:
    data = _valid_policy_dict()
    mutate(data)
    bad = tmp_path / "policy.yml"
    bad.write_text(yaml.safe_dump(data))
    with pytest.raises(PolicyError):
        load_policy(bad, lockfile_names=_LOCKFILE_NAMES, ownership_formats=_OWNERSHIP_FORMATS)


# ── 3. Folder-override resolution ──


_VISUAL_REVIEW_FILE = "products/visual_review/AGENT_APPROVALS.md"
_PRODUCTS_FILE = "products/AGENT_APPROVALS.md"
_PROSE_ONLY_FM = "{}"


def _grant(max_files: int) -> str:
    return f"stamphog:\n  size_gate:\n    max_files: {max_files}"


def _multi_prose(*parts: tuple[str, str]) -> str:
    return "\n\n".join(f"[{path}]\n{prose}" for path, prose in parts)


def _write_agent_policy(root: Path, rel_dir: str, frontmatter: str, prose: str) -> str:
    path = root / rel_dir / "AGENT_APPROVALS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{prose}\n")
    return f"{rel_dir}/AGENT_APPROVALS.md"


def _write_folder_policy(root: Path, frontmatter: str, prose: str = "advisory prose") -> None:
    _write_agent_policy(root, "products/visual_review", frontmatter, prose)


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(policy, "repo_root", lambda: tmp_path)
    return tmp_path


def _scope(eff, path):
    return next(s for s in eff.scopes if s.path == path)


def test_resolve_folder_override_budgets_its_own_files(fake_repo: Path) -> None:
    _write_folder_policy(fake_repo, "stamphog:\n  size_gate:\n    max_files: 50")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py", "products/visual_review/sub/b.py"])
    vr = _scope(eff, _VISUAL_REVIEW_FILE)
    assert vr.max_files == 50
    assert set(vr.files) == {"products/visual_review/a.py", "products/visual_review/sub/b.py"}
    assert _scope(eff, None).files == ()
    assert eff.max_lines == gates.MAX_LINES
    assert eff.invalid_folder_files == ()
    assert eff.folder_prose == "advisory prose"


def test_resolve_mixed_pr_budgets_each_scope_separately(fake_repo: Path) -> None:
    # Mixed leniency: the folder's files keep the folder ceiling, everything
    # else keeps the global ceiling. A stray root file no longer revokes the
    # override, it just has to fit the global budget itself.
    _write_folder_policy(fake_repo, "stamphog:\n  size_gate:\n    max_files: 50")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py", "README.md"])
    assert _scope(eff, _VISUAL_REVIEW_FILE).max_files == 50
    assert _scope(eff, _VISUAL_REVIEW_FILE).files == ("products/visual_review/a.py",)
    assert _scope(eff, None).max_files == gates.MAX_FILES
    assert _scope(eff, None).files == ("README.md",)


@pytest.mark.parametrize(
    "frontmatter",
    [
        pytest.param("stamphog:\n  size_gate:\n    max_lines: 999", id="undelegated-key"),
        pytest.param("stamphog:\n  size_gate:\n    max_files: 99", id="over-ceiling"),
    ],
)
def test_resolve_invalid_folder_file_pools_files_into_global(fake_repo: Path, frontmatter: str) -> None:
    _write_folder_policy(fake_repo, frontmatter)
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    assert [s.path for s in eff.scopes] == [None]
    assert _scope(eff, None).files == ("products/visual_review/a.py",)
    assert eff.invalid_folder_files == (_VISUAL_REVIEW_FILE,)
    assert eff.folder_prose is None


@pytest.mark.usefixtures("fake_repo")
def test_resolve_no_folder_file_uses_global() -> None:
    eff = resolve(gates.POLICY, ["posthog/api/insight.py"])
    assert [s.path for s in eff.scopes] == [None]
    assert _scope(eff, None).max_files == gates.MAX_FILES
    assert eff.invalid_folder_files == ()


def test_resolve_prose_only_folder_file_keeps_global_budget(fake_repo: Path) -> None:
    # No pseudo-scope budget: without a max_files grant the files pool into
    # the global budget, but the advisory prose still reaches the reviewer.
    (fake_repo / "products" / "visual_review").mkdir(parents=True)
    (fake_repo / _VISUAL_REVIEW_FILE).write_text("---\n{}\n---\n\nadvice only\n")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    assert [s.path for s in eff.scopes] == [None]
    assert _scope(eff, None).files == ("products/visual_review/a.py",)
    assert eff.folder_prose == "advice only"


def test_resolve_carries_sanitized_prose(fake_repo: Path) -> None:
    _write_folder_policy(fake_repo, "stamphog:\n  size_gate:\n    max_files: 50", prose="keep\x07this")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    assert eff.folder_prose == "keepthis"


@pytest.mark.parametrize(
    "n_global, expected_ok",
    [
        pytest.param(19, True, id="both-budgets-fit"),
        pytest.param(21, False, id="global-budget-exceeded"),
    ],
)
def test_size_gate_applies_mixed_leniency(n_global: int, expected_ok: bool) -> None:
    # 30 folder-scoped files ride the folder's ceiling while the remaining
    # files are judged against the global ceiling on their own.
    vr_files = [{"filename": f"products/visual_review/f{i}.py", "additions": 5, "deletions": 0} for i in range(30)]
    global_files = [{"filename": f"posthog/api/m{i}.py", "additions": 5, "deletions": 0} for i in range(n_global)]

    pipeline = review_pr.Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = PRData(
        number=1,
        repo="PostHog/posthog",
        title="feat: mixed change",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
        base_ref="master",
        base_sha="base",
        head_sha="head",
        files=vr_files + global_files,
        reviews=[],
        review_comments=[],
        check_runs=[],
    )
    pipeline.effective_policy = EffectivePolicy(
        max_lines=500,
        scopes=(
            ScopeBudget(path=_VISUAL_REVIEW_FILE, max_files=50, files=tuple(f["filename"] for f in vr_files)),
            ScopeBudget(path=None, max_files=20, files=tuple(f["filename"] for f in global_files)),
        ),
    )

    ok, message = pipeline._check_size()
    assert ok is expected_ok
    if not expected_ok:
        assert "global" in message


@pytest.mark.parametrize(
    "parent_fm, child_fm, scope_path, max_files",
    [
        pytest.param(_PROSE_ONLY_FM, _grant(50), _VISUAL_REVIEW_FILE, 50, id="child-grants"),
        pytest.param(_grant(30), _PROSE_ONLY_FM, _PRODUCTS_FILE, 30, id="parent-grants-child-prose-only"),
    ],
)
def test_resolve_child_rides_nearest_grant_and_accumulates_ancestor_prose(
    fake_repo: Path, parent_fm: str, child_fm: str, scope_path: str, max_files: int
) -> None:
    # A child file refines its ancestors, never replaces them: the nearest valid
    # grant on the chain budgets the file, and every valid folder file's prose
    # survives (outermost first).
    _write_agent_policy(fake_repo, "products", parent_fm, "parent guidance")
    _write_agent_policy(fake_repo, "products/visual_review", child_fm, "child guidance")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    scope = _scope(eff, scope_path)
    assert scope.max_files == max_files
    assert scope.files == ("products/visual_review/a.py",)
    assert _scope(eff, None).files == ()
    assert eff.invalid_folder_files == ()
    assert eff.folder_prose == _multi_prose(
        (_PRODUCTS_FILE, "parent guidance"),
        (_VISUAL_REVIEW_FILE, "child guidance"),
    )


def test_resolve_nearest_grant_wins_across_siblings(fake_repo: Path) -> None:
    _write_agent_policy(fake_repo, "products", _grant(30), "parent guidance")
    _write_agent_policy(fake_repo, "products/visual_review", _grant(50), "child guidance")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py", "products/foo.py"])
    assert _scope(eff, _VISUAL_REVIEW_FILE).max_files == 50
    assert _scope(eff, _VISUAL_REVIEW_FILE).files == ("products/visual_review/a.py",)
    assert _scope(eff, _PRODUCTS_FILE).max_files == 30
    assert _scope(eff, _PRODUCTS_FILE).files == ("products/foo.py",)
    assert _scope(eff, None).files == ()


def test_resolve_invalid_child_rides_parent_grant(fake_repo: Path) -> None:
    # An invalid child is treated as absent: it grants nothing and adds no prose,
    # but it does not cancel the granting parent above it.
    _write_agent_policy(fake_repo, "products", _grant(30), "parent guidance")
    _write_agent_policy(fake_repo, "products/visual_review", _grant(99), "child guidance")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    parent_scope = _scope(eff, _PRODUCTS_FILE)
    assert parent_scope.max_files == 30
    assert parent_scope.files == ("products/visual_review/a.py",)
    assert _scope(eff, None).files == ()
    assert eff.invalid_folder_files == (_VISUAL_REVIEW_FILE,)
    assert eff.folder_prose == "parent guidance"


# ── 4. A policy-file-only PR is never T0 (deny wins over allow-listed ext) ──


@pytest.mark.parametrize(
    "path",
    [".stamphog/policy.yml", "some/AGENT_APPROVALS.md", "tools/pr-approval-agent/review_pr.py"],
)
def test_policy_file_only_pr_is_t2_never(path: str) -> None:
    deny = gates.detect_deny_categories([path])
    assert deny == ["stamphog_policy"]
    tier = gates.assign_tier(
        deny_categories=deny,
        allow_listed_only=gates.is_allow_listed_only([path]),
        is_test_only=False,
        has_new_files=False,
        lines_total=1,
        files_changed=1,
        breadth="single-area",
        commit_type="chore",
    )
    assert tier == "T2-never"


# ── 5. Prompt composition wires the guidance file into the system prompt ──


def test_reviewer_system_composes_guidance_and_scaffold() -> None:
    # Wording changes are governed by human review (stamphog_policy deny), not a
    # frozen snapshot; this only guards the composition seam itself.
    guidance = policy.review_guidance_path().read_text()
    assert reviewer.REVIEWER_SYSTEM == guidance + reviewer._REVIEWER_SCAFFOLD_TAIL
    assert "showstoppers" in guidance
    assert "Verdicts:" in reviewer._REVIEWER_SCAFFOLD_TAIL


# ── 6. Stamphog policy files are not trivial at dismiss time ──


@pytest.mark.parametrize(
    "path",
    ["products/visual_review/AGENT_APPROVALS.md", ".stamphog/policy.yml", "tools/pr-approval-agent/gates.py"],
)
def test_policy_paths_not_trivial_at_dismiss_time(path: str) -> None:
    assert gates.is_trivial_at_dismiss_time(path) is False


# ── 7. Folder prose is sanitized and capped ──


def test_folder_prose_stripped_of_control_chars() -> None:
    assert _sanitize_folder_prose("keep\x07this​clean") == "keepthisclean"


def test_folder_prose_capped_with_marker() -> None:
    out = _sanitize_folder_prose("x" * 5000)
    assert out.startswith("x" * 2000)
    assert out.endswith("truncated ...]")
    assert len(out) <= 2000 + 64


def _body_pipeline(fam) -> "review_pr.Pipeline":
    pipeline = review_pr.Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = PRData(
        number=1,
        repo="PostHog/posthog",
        title="feat: change",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
        base_ref="master",
        base_sha="base",
        head_sha="91c4be2aaaa",
        files=[{"filename": "products/visual_review/a.py", "additions": 3, "deletions": 1, "status": "M"}],
        reviews=[{"user": "greptile-apps[bot]", "state": "COMMENTED", "is_current_head": True}],
        review_comments=[],
        check_runs=[],
    )
    pipeline.reviewer_output = {"verdict": "APPROVE", "reasoning": "No showstoppers.", "risk": "low", "issues": []}
    pipeline.classification = {
        "familiarity": fam,
        "assurance": {"head_approvals": [], "head_commented_users": ["greptile-apps[bot]"]},
    }
    pipeline.effective_policy = EffectivePolicy(
        max_lines=500,
        scopes=(
            ScopeBudget(path=_VISUAL_REVIEW_FILE, max_files=50, files=("products/visual_review/a.py",)),
            ScopeBudget(path=None, max_files=20, files=()),
        ),
    )
    pipeline.gate_results = [review_pr.GateResult("size", True, "4L, 1F substantive")]
    return pipeline


def test_review_body_leads_with_reasoning_and_folds_mechanics() -> None:
    fam = AuthorFamiliarity(
        band="STRONG",
        blame_overlap_pct=82.0,
        modified_lines_owned=41,
        modified_lines_total=50,
        prior_prs_in_paths=11,
        days_since_last_touch=12,
        files_prev_count=1,
        files_total=1,
        capped=False,
        top_prior_authors=(),
    )
    body = _body_pipeline(fam)._render_review_body()
    assert body is not None
    reasoning_pos = body.index("No showstoppers.")
    assert reasoning_pos == 0
    assert body.index("familiarity STRONG") > reasoning_pos
    assert "greptile-apps[bot] reviewed the current head." in body
    assert "<details>" in body and body.index("<details>") > body.index("familiarity STRONG")
    assert "| size | ✓ | 4L, 1F substantive |" in body
    assert "reviewed head `91c4be2`" in body


def test_review_body_without_familiarity_has_no_familiarity_bullet() -> None:
    body = _body_pipeline(None)._render_review_body()
    assert body is not None
    assert "familiarity" not in body.lower()
