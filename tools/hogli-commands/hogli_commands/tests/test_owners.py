from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hogli_commands.owners import fmt as fmt_module
from hogli_commands.owners.cli import _consolidation_suggestions, _reserved_location_error
from hogli_commands.owners.conversion import Converter, parse_soft_file, render_owners_yaml
from hogli_commands.owners.fmt import CanonicalPlacer, CanonicalPlan
from hogli_commands.owners.legacy_diff import DiffClass, LegacyOwners, classify
from hogli_commands.owners.matcher import path_matches_pattern
from hogli_commands.owners.resolver import OwnersResolver


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("/foo/bar", "foo/bar", True),
        ("/foo/bar", "foo/bar/baz.py", True),
        ("/foo/bar", "x/foo/bar", False),
        ("foo", "a/b/foo", True),
        ("foo", "a/b/foo/c", True),
        ("*.js", "a/b/c.js", True),
        ("*.js", "a/b/c.ts", False),
        ("/docs/*", "docs/x.md", True),
        ("/docs/*", "docs/a/b.md", False),
        ("a/**/b", "a/b", True),
        ("a/**/b", "a/x/y/b", True),
        ("a/**/b", "a/b/c", True),
        ("**/foo", "a/foo", True),
        ("**", "anything/x", True),
        ("docs/", "docs/x/y", True),
        ("docker-compose*.yml", "a/b/docker-compose.dev.yml", True),
    ],
)
def test_matcher_vectors(pattern: str, path: str, expected: bool) -> None:
    assert path_matches_pattern(pattern, path) is expected


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def resolver_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "owners.yaml",
        "version: 1\nowners: null\nrules:\n  - match: Dockerfile\n    owners: [team-devex]\n",
    )
    _write(
        tmp_path,
        "posthog/owners.yaml",
        "version: 1\nowners: [team-a]\ncontact:\n  slack: '#custom'\n"
        "rules:\n  - match: '/vendor/**'\n    owners: null\n  - match: legacy.py\n    owners: [team-legacy]\n",
    )
    _write(tmp_path, "posthog/sub/owners.yaml", "version: 1\nowners: [team-b]\n")
    _write(tmp_path, "posthog/noinherit/owners.yaml", "version: 1\ninherit: false\nowners: [team-c]\n")
    _write(tmp_path, "products/foo/product.yaml", "name: Foo\nowners:\n  - team-foo\n")
    _write(tmp_path, "products/bar/product.yaml", "name: Bar\nowners:\n  - team-CHANGEME\n")
    return tmp_path


@pytest.mark.parametrize(
    "path,owners,unowned_by_design",
    [
        ("Dockerfile", ["team-devex"], False),
        ("README.md", None, True),
        ("posthog/x.py", ["team-a"], False),
        ("posthog/legacy.py", ["team-legacy"], False),
        ("posthog/vendor/lib.py", None, True),
        ("posthog/sub/y.py", ["team-b"], False),
        ("posthog/sub/legacy.py", ["team-b"], False),
        ("posthog/noinherit/z.py", ["team-c"], False),
        ("products/foo/thing.py", ["team-foo"], False),
        ("products/bar/thing.py", None, True),
        ("other/legacy.py", None, True),
    ],
)
def test_resolver_precedence(resolver_repo: Path, path: str, owners: list[str] | None, unowned_by_design: bool) -> None:
    r = OwnersResolver(repo_root=resolver_repo).resolve(path)
    assert r.owners == owners
    assert r.unowned_by_design is unowned_by_design


def test_resolver_no_contribution_is_unowned_not_exempt(tmp_path: Path) -> None:
    _write(tmp_path, "posthog/owners.yaml", "version: 1\nowners: [team-a]\n")
    resolver = OwnersResolver(repo_root=tmp_path)
    r = resolver.resolve("other/file.py")
    assert r.owners is None
    assert r.unowned_by_design is False
    assert resolver.unowned(["other/file.py", "posthog/x.py"]) == ["other/file.py"]


@pytest.mark.parametrize(
    "path,slack",
    [
        ("posthog/x.py", "#custom"),
        ("posthog/sub/y.py", "#custom"),
        ("posthog/noinherit/z.py", "#team-c"),
        ("products/foo/thing.py", "#team-foo"),
    ],
)
def test_resolver_slack_derivation_and_fallthrough(resolver_repo: Path, path: str, slack: str) -> None:
    assert OwnersResolver(repo_root=resolver_repo).resolve(path).slack == slack


@pytest.fixture
def conversion_repo(tmp_path: Path) -> Path:
    for d in [
        "frontend/src/scenes/surveys",
        ".github/workflows",
        "docs/onboarding/x",
        "posthog",
        "products/foo",
        "products/bar",
        "products/baz/backend/migrations",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_conversion_mapping(conversion_repo: Path) -> None:
    soft = "\n".join(
        [
            "frontend/src/scenes/surveys/ @PostHog/team-surveys",
            "posthog/email.py @PostHog/team-platform-features",
            ".github/workflows/** @PostHog/team-devex",
            ".github/workflows/ci-x.yml @PostHog/team-devex @PostHog/team-ai-gateway",
            "products/foo/** @PostHog/team-foo",
            "products/bar/** @PostHog/team-bar",
            "products/baz/backend/migrations/** @PostHog/team-baz",
            "Dockerfile @PostHog/team-devex",
            "docs/onboarding/x/ @PostHog/team-x",
            ".agents/skills/ingestion-*/ @PostHog/team-ingestion",
            "bin/ @PostHog/team-devex",
        ]
    )
    product_owners = {"foo": ["team-foo"], "bar": ["team-other"], "baz": ["team-baz"]}
    summary = Converter(conversion_repo, product_owners).convert(parse_soft_file(soft))

    assert summary.files["frontend/src/scenes/surveys"].owners == ["team-surveys"]

    posthog = summary.files["posthog"]
    assert posthog.owners == []
    assert posthog.rules == [("/email.py", ["team-platform-features"])]
    assert render_owners_yaml(posthog).splitlines()[1] == "owners: []"

    workflows = summary.files[".github/workflows"]
    assert workflows.owners == ["team-devex"]
    assert ("/ci-x.yml", ["team-devex", "team-ai-gateway"]) in workflows.rules

    assert summary.files["products/baz/backend/migrations"].owners == ["team-baz"]

    root = summary.files[""]
    assert root.owners == []
    assert ("Dockerfile", ["team-devex"]) in root.rules
    assert ("bin/", ["team-devex"]) in root.rules
    assert "bin" not in summary.files
    assert render_owners_yaml(root).splitlines()[1] == "owners: null"

    assert not any("*" in d for d in summary.files)
    assert ("/ingestion-*/", ["team-ingestion"]) in summary.files[".agents/skills"].rules

    assert any("products/foo/**" in s for s in summary.redundant_skips)
    assert any("products/bar/**" in s for s in summary.needs_decision)
    assert "products/foo" not in summary.files
    assert "products/bar" not in summary.files


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ({"a"}, {"a"}, DiffClass.IDENTICAL),
        (set(), set(), DiffClass.IDENTICAL),
        ({"a", "b"}, {"a"}, DiffClass.NARROWED),
        ({"a"}, set(), DiffClass.ORPHANED),
        (set(), {"a"}, DiffClass.NEWLY_OWNED),
        ({"a"}, {"a", "b"}, DiffClass.EXPANDED),
        ({"a", "b"}, {"a", "c"}, DiffClass.EXPANDED),
    ],
)
def test_diff_classify(old: set[str], new: set[str], expected: DiffClass) -> None:
    assert classify(old, new) == expected


@pytest.mark.parametrize(
    "rel,reserved",
    [
        (".github/workflows/owners.yaml", True),
        (".github/workflows/sub/owners.yaml", True),
        ("products/error_tracking/mcp/owners.yaml", True),
        ("products/foo/mcp/sub/owners.yaml", True),
        (".github/owners.yaml", False),
        ("products/foo/backend/owners.yaml", False),
        ("mcp/owners.yaml", False),
    ],
)
def test_reserved_location_error(rel: str, reserved: bool) -> None:
    assert (_reserved_location_error(rel) is not None) is reserved


@pytest.mark.parametrize(
    "owners_dirs,expected",
    [
        # Branch point with enough simple files spread across children fires.
        ({"a/b": True, "a/c": True, "a/d": True, "a/e": True, "a/f": True}, [("a", 5)]),
        # Exactly at threshold (3) across ≥2 children fires.
        ({"a/b": True, "a/c": True, "a/d": True}, [("a", 3)]),
        # Below threshold stays quiet.
        ({"a/b": True, "a/c": True}, []),
        # A passthrough ancestor (all files under one child) yields the deeper branch point only.
        (
            {"a/b/1": True, "a/b/2": True, "a/b/3": True, "a/b/4": True, "a/b/5": True},
            [("a/b", 5)],
        ),
        # A non-simple file between parent and files keeps that subtree out of the count.
        (
            {
                "a/b": True,
                "a/c": True,
                "a/mid": False,
                "a/mid/f": True,
                "a/mid/g": True,
            },
            [],
        ),
        # Nested branch points report only the deepest.
        (
            {"a/b/1": True, "a/b/2": True, "a/b/3": True, "a/b/4": True, "a/b/5": True, "a/c": True, "a/d": True},
            [("a/b", 5)],
        ),
    ],
)
def test_consolidation_suggestions(owners_dirs: dict[str, bool], expected: list[tuple[str, int]]) -> None:
    assert _consolidation_suggestions(owners_dirs) == expected


def test_legacy_owners_unions_matching_rules(tmp_path: Path) -> None:
    soft_text = (
        "posthog/x/ @PostHog/team-a\nposthog/x/y.py @PostHog/team-b\nproducts/foo/** @rafael @PostHog/team-foo\n"
    )
    _write(tmp_path, "products/foo/product.yaml", "name: Foo\nowners:\n  - team-foo\n  - '@handle'\n")
    _write(tmp_path, "products/bar/product.yaml", "name: Bar\nowners:\n  - team-CHANGEME\n")
    legacy = LegacyOwners(tmp_path, soft_text)

    assert legacy.owners_of("posthog/x/y.py") == {"team-a", "team-b"}
    assert legacy.owners_of("products/foo/z.py") == {"@rafael", "team-foo"}
    assert legacy.owners_of("products/bar/z.py") == set()


def _fmt_plan(tmp_path: Path, files: dict[str, str]) -> CanonicalPlan:
    for rel, text in files.items():
        _write(tmp_path, rel, text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return CanonicalPlacer(OwnersResolver(repo_root=tmp_path)).build()


def test_fmt_folds_dedicated_child_into_pinned_parent(tmp_path: Path) -> None:
    # `a` is a pinned carrier (non-simple, has a contact); `a/b` is a dedicated
    # single-statement file. Canonical folds b's statement into a and drops the file.
    plan = _fmt_plan(
        tmp_path,
        {
            "a/owners.yaml": "version: 1\nowners: [team-a]\ncontact:\n  slack: '#a'\n",
            "a/f.py": "x",
            "a/b/owners.yaml": "version: 1\nowners: [team-b]\n",
            "a/b/g.py": "x",
            "r1.py": "x",
            "r2.py": "x",
        },
    )
    assert plan.deletions == ["a/b/owners.yaml"]
    assert plan.additions == {"a/owners.yaml": ["/b/ -> [team-b]"]}
    assert plan.creations == []


def test_fmt_splits_when_carrier_exceeds_capacity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A pinned parent above enough owned sibling dirs to blow past MAX_RULES opens a
    # dedicated child facility under the shared prefix to absorb the overflow.
    monkeypatch.setattr(fmt_module, "MAX_RULES", 3)
    files = {
        "P/owners.yaml": "version: 1\nowners: [team-p]\ncontact:\n  slack: '#p'\n",
        "P/f.py": "x",
        "r1.py": "x",
        "r2.py": "x",
    }
    for i in range(4):
        files[f"P/c/s{i}/owners.yaml"] = f"version: 1\nowners: [team-{i}]\n"
        files[f"P/c/s{i}/g.py"] = "x"
    plan = _fmt_plan(tmp_path, files)
    assert "P/c/owners.yaml" in plan.creations


def test_fmt_never_exiles_singleton_rules_on_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # When every overflow group is a single statement, splitting would recreate the
    # per-dir single-purpose files fmt exists to remove — the cap is soft instead.
    monkeypatch.setattr(fmt_module, "MAX_RULES", 3)
    files = {
        "P/owners.yaml": "version: 1\nowners: [team-p]\ncontact:\n  slack: '#p'\n",
        "P/f.py": "x",
        "r1.py": "x",
        "r2.py": "x",
    }
    for i in range(4):
        files[f"P/d{i}/owners.yaml"] = f"version: 1\nowners: [team-{i}]\n"
        files[f"P/d{i}/g.py"] = "x"
    plan = _fmt_plan(tmp_path, files)
    assert plan.creations == []


def test_fmt_product_yaml_is_a_free_carrier(tmp_path: Path) -> None:
    # The product manifest already declares ownership, so no dedicated owners.yaml is
    # proposed and nothing is added — a single-statement product is not flagged.
    plan = _fmt_plan(
        tmp_path,
        {
            "products/foo/product.yaml": "name: Foo\nowners:\n  - team-foo\n",
            "products/foo/x.py": "x",
            "r1.py": "x",
            "r2.py": "x",
        },
    )
    assert plan.is_canonical


def test_fmt_never_places_rules_on_a_product_yaml_dir(tmp_path: Path) -> None:
    # A product.yaml manifest only exposes its owners list — it cannot physically hold
    # rules, and an owners.yaml next to it is a lint error. A differently-owned subtree
    # below a product must keep its own file or fold to an ancestor, never produce
    # additions keyed on the product dir.
    plan = _fmt_plan(
        tmp_path,
        {
            "products/foo/product.yaml": "name: Foo\nowners:\n  - team-foo\n",
            "products/foo/x.py": "x",
            "products/foo/sub/owners.yaml": "version: 1\nowners: [team-bar]\n",
            "products/foo/sub/y.py": "x",
            "r1.py": "x",
            "r2.py": "x",
        },
    )
    assert "products/foo/owners.yaml" not in plan.additions
    assert "products/foo/owners.yaml" not in plan.creations


def test_fmt_leaves_glob_files_untouched(tmp_path: Path) -> None:
    # A glob rule is crosscutting, not a tree boundary — fmt must not rewrite it.
    plan = _fmt_plan(
        tmp_path,
        {
            "d/owners.yaml": "version: 1\nowners: []\nrules:\n  - match: '*.py'\n    owners: [team-a]\n",
            "d/x.py": "x",
            "d/y.py": "x",
        },
    )
    assert plan.is_canonical


def test_fmt_is_idempotent_on_canonical_layout(tmp_path: Path) -> None:
    # A layout already in canonical form (child folded into the pinned parent) yields
    # no proposed moves.
    plan = _fmt_plan(
        tmp_path,
        {
            "a/owners.yaml": "version: 1\nowners: [team-a]\ncontact:\n  slack: '#a'\n"
            "rules:\n  - match: '/b/'\n    owners: [team-b]\n",
            "a/f.py": "x",
            "a/b/g.py": "x",
            "r1.py": "x",
            "r2.py": "x",
        },
    )
    assert plan.is_canonical


def test_fmt_equivalence_proof_catches_a_wrong_layout(tmp_path: Path) -> None:
    # The built-in proof must hard-fail if the proposed layout ever resolves a path
    # differently from the current one — corrupt the expected map and confirm it raises.
    for rel, text in {"a/owners.yaml": "version: 1\nowners: [team-a]\n", "a/f.py": "x"}.items():
        _write(tmp_path, rel, text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    placer = CanonicalPlacer(OwnersResolver(repo_root=tmp_path))
    with pytest.raises(AssertionError):
        placer._prove({}, {"a/f.py": ("team-wrong",)})
