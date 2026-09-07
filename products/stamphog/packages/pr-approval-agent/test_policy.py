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
OLD_MAX_LINES = 800
OLD_MAX_FILES = 30

# ── 1. Equality snapshot: loaded policy matches pre-extraction literals ──


def test_deny_defs_equal_pre_extraction_excluding_stamphog_policy() -> None:
    live = {k: v for k, v in gates._DENY_PATTERN_DEFS.items() if k != "stamphog_policy"}
    assert live == OLD_DENY_PATTERN_DEFS


def test_allow_and_size_equal_pre_extraction() -> None:
    assert set(gates.ALLOW_ONLY_EXTENSIONS) == OLD_ALLOW_ONLY_EXTENSIONS
    assert list(gates.ALLOW_PATH_PATTERNS) == OLD_ALLOW_PATH_PATTERNS
    assert gates.MAX_LINES == OLD_MAX_LINES
    assert gates.MAX_FILES == OLD_MAX_FILES


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


def _ceiling_under_global_default(d: dict) -> None:
    d["size_gate"]["max_lines"] = d["overrides"]["size_gate.max_lines"]["ceiling"] + 1


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
    d["ownership"]["sources"][0] = {"format": "hogli-resolver", "glob": "products/*/product.yaml"}


@pytest.mark.parametrize(
    "mutate",
    [
        _unknown_top_level_key,
        _empty_pattern_list,
        _invalid_regex,
        _drop_self_governance,
        _out_of_contract_delegation,
        _ceiling_under_global_default,
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


def test_server_owned_digest_section_is_allowed_and_ignored(tmp_path: Path) -> None:
    # The hosted server declares a `digest:` top-level section it parses itself; the engine must
    # tolerate (not require, not read) it, or any repo with a digest channel crashes every review.
    data = _valid_policy_dict()
    data["digest"] = {"channel": "eng-merges"}
    path = tmp_path / "policy.yml"
    path.write_text(yaml.safe_dump(data))
    loaded = load_policy(path, lockfile_names=_LOCKFILE_NAMES, ownership_formats=_OWNERSHIP_FORMATS)
    assert loaded.version == 1


# ── 3. Folder-override resolution ──


_VISUAL_REVIEW_FILE = "products/visual_review/AGENT_APPROVALS.md"
_PRODUCTS_FILE = "products/AGENT_APPROVALS.md"
_PROSE_ONLY_FM = "{}"


def _grant(max_files: int | None = None, max_lines: int | None = None) -> str:
    lines = ["stamphog:", "  size_gate:"]
    if max_files is not None:
        lines.append(f"    max_files: {max_files}")
    if max_lines is not None:
        lines.append(f"    max_lines: {max_lines}")
    return "\n".join(lines)


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


def _file_scope(eff, path):
    return next(s for s in eff.file_scopes if s.path == path)


def _line_scope(eff, path):
    return next(s for s in eff.line_scopes if s.path == path)


def test_resolve_folder_override_budgets_its_own_files(fake_repo: Path) -> None:
    _write_folder_policy(fake_repo, "stamphog:\n  size_gate:\n    max_files: 50")
    changed = ["products/visual_review/a.py", "products/visual_review/sub/b.py"]
    eff = resolve(gates.POLICY, changed)
    vr = _file_scope(eff, _VISUAL_REVIEW_FILE)
    assert vr.ceiling == 50
    assert set(vr.files) == set(changed)
    assert _file_scope(eff, None).files == ()
    # Granting max_files alone leaves the lines in the global pool, at the global ceiling.
    global_lines = _line_scope(eff, None)
    assert global_lines.ceiling == gates.MAX_LINES
    assert set(global_lines.files) == set(changed)
    assert [s.path for s in eff.line_scopes] == [None]
    assert eff.invalid_folder_files == ()
    assert eff.folder_prose == "advisory prose"


def test_resolve_mixed_pr_budgets_each_scope_separately(fake_repo: Path) -> None:
    # Mixed leniency: the folder's files keep the folder ceiling, everything
    # else keeps the global ceiling. A stray root file no longer revokes the
    # override, it just has to fit the global budget itself.
    _write_folder_policy(fake_repo, "stamphog:\n  size_gate:\n    max_files: 50")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py", "README.md"])
    assert _file_scope(eff, _VISUAL_REVIEW_FILE).ceiling == 50
    assert _file_scope(eff, _VISUAL_REVIEW_FILE).files == ("products/visual_review/a.py",)
    assert _file_scope(eff, None).ceiling == gates.MAX_FILES
    assert _file_scope(eff, None).files == ("README.md",)


@pytest.mark.parametrize(
    "frontmatter, expected_file_budget, expected_line_budget",
    [
        pytest.param(_grant(max_files=50), (_VISUAL_REVIEW_FILE, 50), (None, gates.MAX_LINES), id="files-only"),
        pytest.param(_grant(max_lines=1000), (None, gates.MAX_FILES), (_VISUAL_REVIEW_FILE, 1000), id="lines-only"),
        pytest.param(
            _grant(max_files=50, max_lines=1000),
            (_VISUAL_REVIEW_FILE, 50),
            (_VISUAL_REVIEW_FILE, 1000),
            id="both-keys",
        ),
    ],
)
def test_resolve_budgets_each_ceiling_independently(
    fake_repo: Path,
    frontmatter: str,
    expected_file_budget: tuple[str | None, int],
    expected_line_budget: tuple[str | None, int],
) -> None:
    # Granting one ceiling must not open a second budget for the other: a
    # lines-only folder still counts its files against the one global file
    # budget, so it can never double how many files a PR may touch.
    _write_folder_policy(fake_repo, frontmatter)
    eff = resolve(gates.POLICY, ["products/visual_review/a.py", "README.md"])
    for (path, ceiling), scopes in ((expected_file_budget, eff.file_scopes), (expected_line_budget, eff.line_scopes)):
        governing = next(s for s in scopes if "products/visual_review/a.py" in s.files)
        assert (governing.path, governing.ceiling) == (path, ceiling)
        # A file outside the folder never rides its grant.
        assert next(s for s in scopes if s.path is None).files[-1] == "README.md"


@pytest.mark.parametrize(
    "frontmatter",
    [
        pytest.param("stamphog:\n  tiers:\n    max_files: 10", id="undelegated-key"),
        pytest.param("stamphog:\n  size_gate:\n    breadth: single-area", id="undelegated-size-gate-key"),
        pytest.param("stamphog:\n  size_gate: {}", id="empty-grant"),
        pytest.param(_grant(max_files=99), id="files-over-ceiling"),
        pytest.param(_grant(max_lines=1001), id="lines-over-ceiling"),
        pytest.param(_grant(max_files=50, max_lines=1001), id="one-key-over-ceiling"),
    ],
)
def test_resolve_invalid_folder_file_pools_files_into_global(fake_repo: Path, frontmatter: str) -> None:
    _write_folder_policy(fake_repo, frontmatter)
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    assert [s.path for s in eff.file_scopes] == [None]
    assert [s.path for s in eff.line_scopes] == [None]
    assert _file_scope(eff, None).files == ("products/visual_review/a.py",)
    assert eff.invalid_folder_files == (_VISUAL_REVIEW_FILE,)
    assert eff.folder_prose is None


@pytest.mark.usefixtures("fake_repo")
def test_resolve_no_folder_file_uses_global() -> None:
    eff = resolve(gates.POLICY, ["posthog/api/insight.py"])
    assert [s.path for s in eff.file_scopes] == [None]
    assert _file_scope(eff, None).ceiling == gates.MAX_FILES
    assert eff.invalid_folder_files == ()


@pytest.mark.parametrize(
    "frontmatter, expected_line_roof",
    [
        pytest.param(None, gates.MAX_LINES, id="no-grant-keeps-the-global-total"),
        pytest.param(_grant(max_lines=200), gates.MAX_LINES, id="grant-under-the-global-default"),
        pytest.param(_grant(max_lines=1000), 1000, id="grant-over-the-global-default"),
    ],
)
def test_roof_is_the_most_generous_ceiling_in_play(
    fake_repo: Path, frontmatter: str | None, expected_line_roof: int
) -> None:
    # A folder may grant under the global default, so the roof reads the global
    # pool too. It is always a scope, which keeps the roof from dropping below
    # the global ceiling.
    if frontmatter is not None:
        _write_folder_policy(fake_repo, frontmatter)
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    assert eff.line_roof == expected_line_roof
    assert eff.file_roof == gates.MAX_FILES


def test_resolve_prose_only_folder_file_keeps_global_budget(fake_repo: Path) -> None:
    # No pseudo-scope budget: without a max_files grant the files pool into
    # the global budget, but the advisory prose still reaches the reviewer.
    (fake_repo / "products" / "visual_review").mkdir(parents=True)
    (fake_repo / _VISUAL_REVIEW_FILE).write_text("---\n{}\n---\n\nadvice only\n")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    assert [s.path for s in eff.file_scopes] == [None]
    assert _file_scope(eff, None).files == ("products/visual_review/a.py",)
    assert eff.folder_prose == "advice only"


def test_resolve_carries_sanitized_prose(fake_repo: Path) -> None:
    _write_folder_policy(fake_repo, "stamphog:\n  size_gate:\n    max_files: 50", prose="keep\x07this")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    assert eff.folder_prose == "keepthis"


def _size_pipeline(vr_files: list[dict], global_files: list[dict]) -> "review_pr.Pipeline":
    # The folder scope carries the higher ceiling on both keys.
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
    vr_names = tuple(f["filename"] for f in vr_files)
    global_names = tuple(f["filename"] for f in global_files)
    pipeline.effective_policy = EffectivePolicy(
        file_scopes=(
            ScopeBudget(path=_VISUAL_REVIEW_FILE, ceiling=50, files=vr_names),
            ScopeBudget(path=None, ceiling=20, files=global_names),
        ),
        line_scopes=(
            ScopeBudget(path=_VISUAL_REVIEW_FILE, ceiling=1000, files=vr_names),
            ScopeBudget(path=None, ceiling=500, files=global_names),
        ),
    )
    return pipeline


@pytest.mark.parametrize(
    "vr_additions, global_additions, n_global, expected_ok, expected_where",
    [
        pytest.param(5, 5, 19, True, None, id="both-budgets-fit"),
        pytest.param(5, 5, 21, False, "global", id="global-file-budget-exceeded"),
        pytest.param(5, 30, 19, False, "global", id="global-line-budget-exceeded"),
        pytest.param(30, 5, 19, True, None, id="folder-lines-exceed-global-ceiling-but-fit-own"),
        pytest.param(40, 5, 19, False, _VISUAL_REVIEW_FILE, id="folder-line-budget-exceeded"),
    ],
)
def test_size_gate_applies_mixed_leniency(
    vr_additions: int, global_additions: int, n_global: int, expected_ok: bool, expected_where: str | None
) -> None:
    # 30 folder-scoped files ride the folder's ceilings while the remaining
    # files are judged against the global ceilings on their own.
    vr_files = [
        {"filename": f"products/visual_review/f{i}.py", "additions": vr_additions, "deletions": 0} for i in range(30)
    ]
    global_files = [
        {"filename": f"posthog/api/m{i}.py", "additions": global_additions, "deletions": 0} for i in range(n_global)
    ]

    ok, message = _size_pipeline(vr_files, global_files)._check_size()
    assert ok is expected_ok
    if expected_where is not None:
        assert f"in {expected_where}" in message


@pytest.mark.parametrize(
    "n_vr, vr_additions, n_global, global_additions, expected_roof",
    [
        pytest.param(30, 30, 19, 26, "1000L", id="line-roof"),
        pytest.param(45, 1, 19, 1, "50F", id="file-roof"),
    ],
)
def test_size_gate_roof_bounds_the_whole_pr(
    n_vr: int, vr_additions: int, n_global: int, global_additions: int, expected_roof: str
) -> None:
    # Every scope fits its own budget here. Without a roof the PR total would
    # grow with the number of granting folders it touches.
    vr_files = [
        {"filename": f"products/visual_review/f{i}.py", "additions": vr_additions, "deletions": 0} for i in range(n_vr)
    ]
    global_files = [
        {"filename": f"posthog/api/m{i}.py", "additions": global_additions, "deletions": 0} for i in range(n_global)
    ]

    ok, message = _size_pipeline(vr_files, global_files)._check_size()
    assert ok is False
    assert "across the whole PR" in message
    assert f"roof is {expected_roof}" in message


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
    scope = _file_scope(eff, scope_path)
    assert scope.ceiling == max_files
    assert scope.files == ("products/visual_review/a.py",)
    assert _file_scope(eff, None).files == ()
    assert eff.invalid_folder_files == ()
    assert eff.folder_prose == _multi_prose(
        (_PRODUCTS_FILE, "parent guidance"),
        (_VISUAL_REVIEW_FILE, "child guidance"),
    )


def test_resolve_nearest_grant_wins_across_siblings(fake_repo: Path) -> None:
    _write_agent_policy(fake_repo, "products", _grant(30), "parent guidance")
    _write_agent_policy(fake_repo, "products/visual_review", _grant(50), "child guidance")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py", "products/foo.py"])
    assert _file_scope(eff, _VISUAL_REVIEW_FILE).ceiling == 50
    assert _file_scope(eff, _VISUAL_REVIEW_FILE).files == ("products/visual_review/a.py",)
    assert _file_scope(eff, _PRODUCTS_FILE).ceiling == 30
    assert _file_scope(eff, _PRODUCTS_FILE).files == ("products/foo.py",)
    assert _file_scope(eff, None).files == ()


def test_resolve_walks_the_chain_separately_for_each_ceiling(fake_repo: Path) -> None:
    # The child grants lines only, so its files still share the parent's one file
    # budget rather than getting a second one of their own.
    _write_agent_policy(fake_repo, "products", _grant(max_files=50), "parent guidance")
    _write_agent_policy(fake_repo, "products/visual_review", _grant(max_lines=1000), "child guidance")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py", "products/foo.py"])
    parent_files = _file_scope(eff, _PRODUCTS_FILE)
    assert parent_files.ceiling == 50
    assert set(parent_files.files) == {"products/visual_review/a.py", "products/foo.py"}
    assert [s.path for s in eff.file_scopes] == [_PRODUCTS_FILE, None]
    child_lines = _line_scope(eff, _VISUAL_REVIEW_FILE)
    assert child_lines.ceiling == 1000
    assert child_lines.files == ("products/visual_review/a.py",)
    global_lines = _line_scope(eff, None)
    assert global_lines.ceiling == gates.MAX_LINES
    assert global_lines.files == ("products/foo.py",)


def test_resolve_invalid_child_rides_parent_grant(fake_repo: Path) -> None:
    # An invalid child is treated as absent: it grants nothing and adds no prose,
    # but it does not cancel the granting parent above it.
    _write_agent_policy(fake_repo, "products", _grant(30), "parent guidance")
    _write_agent_policy(fake_repo, "products/visual_review", _grant(99), "child guidance")
    eff = resolve(gates.POLICY, ["products/visual_review/a.py"])
    parent_scope = _file_scope(eff, _PRODUCTS_FILE)
    assert parent_scope.ceiling == 30
    assert parent_scope.files == ("products/visual_review/a.py",)
    assert _file_scope(eff, None).files == ()
    assert eff.invalid_folder_files == (_VISUAL_REVIEW_FILE,)
    assert eff.folder_prose == "parent guidance"


# ── 4. A policy-file-only PR is never T0 (deny wins over allow-listed ext) ──


@pytest.mark.parametrize(
    "path",
    [
        ".stamphog/policy.yml",
        "some/AGENT_APPROVALS.md",
        "products/stamphog/packages/pr-approval-agent/review_pr.py",
        # A vendored copy keeps the engine under tools/, and the same deny must still cover it.
        "tools/pr-approval-agent/review_pr.py",
    ],
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


# ── 6. Folder prose is sanitized and capped ──


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
        file_scopes=(
            ScopeBudget(path=_VISUAL_REVIEW_FILE, ceiling=50, files=("products/visual_review/a.py",)),
            ScopeBudget(path=None, ceiling=20, files=()),
        ),
        line_scopes=(
            ScopeBudget(path=_VISUAL_REVIEW_FILE, ceiling=1000, files=("products/visual_review/a.py",)),
            ScopeBudget(path=None, ceiling=500, files=()),
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
