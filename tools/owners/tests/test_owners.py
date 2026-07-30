from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from posthog_owners import fmt as fmt_module
from posthog_owners.cli import _consolidation_suggestions, _reserved_location_error
from posthog_owners.fmt import CanonicalPlacer, CanonicalPlan
from posthog_owners.matcher import path_matches_pattern
from posthog_owners.resolver import OwnersResolver
from posthog_owners.schema import is_simple_owners_file, parse_owners_file


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
        "version: 1\nowners: [team-a]\n"
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


def test_rule_level_inherit_false_cuts_ancestors_for_matching_paths_only(tmp_path: Path) -> None:
    _write(tmp_path, "a/owners.yaml", "version: 1\nowners: [team-a]\n")
    _write(
        tmp_path,
        "a/b/owners.yaml",
        "version: 1\nowners: []\nrules:\n  - match: '/cut/'\n    owners: [team-b]\n    inherit: false\n",
    )
    resolver = OwnersResolver(repo_root=tmp_path)
    cut = resolver.resolve("a/b/cut/x.py")
    assert cut.owners == ["team-b"]  # rule-level inherit:false + own owners win
    other = resolver.resolve("a/b/other.py")
    assert other.owners == ["team-a"]  # non-matching path still inherits the ancestor


def test_rule_level_inherit_true_restores_ancestors_under_file_level_cut(tmp_path: Path) -> None:
    # The inverse direction: the file cuts inheritance, a rule opts its paths
    # back in. The cut must apply after rule overrides — applying it while
    # collecting files made this documented override a silent no-op.
    _write(tmp_path, "owners.yaml", "version: 1\nowners: [team-root]\n")
    _write(
        tmp_path,
        "a/owners.yaml",
        "version: 1\nowners: []\ninherit: false\nrules:\n  - match: '/keep/'\n    inherit: true\n",
    )
    resolver = OwnersResolver(repo_root=tmp_path)
    assert resolver.resolve("a/x.py").owners is None  # file-level cut holds
    assert resolver.resolve("a/keep/x.py").owners == ["team-root"]  # rule restores


def test_invalid_rule_glob_is_a_schema_error_not_a_crash(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a/owners.yaml",
        "version: 1\nowners: [team-a]\nrules:\n  - match: 'a***b'\n    owners: [team-b]\n",
    )
    parsed, errors = parse_owners_file(
        (tmp_path / "a/owners.yaml").read_text(), path=tmp_path / "a/owners.yaml", directory="a"
    )
    assert any("invalid match pattern" in e for e in errors)
    assert parsed is not None and parsed.rules == []  # rule dropped, file still usable
    # The resolver never sees the uncompilable rule, so resolution doesn't raise.
    assert OwnersResolver(repo_root=tmp_path).resolve("a/x.py").owners == ["team-a"]


@pytest.mark.parametrize(
    "owners_yaml,expected",
    [
        ("owners: team-a", ["team-a"]),
        ("owners: '@someone'", ["@someone"]),
        ("owners: ''", None),  # empty string is a schema error, not a bogus [''] owner
        ("owners: ['']", None),  # a [''] list would count as covered while the assigner pings nobody
        ("owners: [team-a, '']", None),
    ],
)
def test_bare_string_owners_normalizes_to_single_element_list(
    tmp_path: Path, owners_yaml: str, expected: list[str] | None
) -> None:
    text = f"version: 1\n{owners_yaml}\nrules:\n  - match: 'sub/'\n    {owners_yaml}\n"
    parsed, errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    if expected is None:
        assert any("'owners' must be" in e for e in errors)
    else:
        assert errors == []
        assert parsed is not None
        assert parsed.owners == expected
        assert parsed.rules[0].owners == expected


def test_multi_match_explodes_to_one_rule_per_pattern(tmp_path: Path) -> None:
    # A list `match:` becomes one OwnersRule per pattern, in order, each carrying the
    # rule's shared owners/status — so resolver/fmt/lint keep seeing single-pattern rules.
    text = (
        "version: 1\nowners: [team-a]\n"
        "rules:\n  - match: [Dockerfile, 'docker-compose*.yml']\n    owners: [team-infra]\n    status: generated\n"
    )
    parsed, errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert errors == []
    assert parsed is not None
    assert [r.match for r in parsed.rules] == ["Dockerfile", "docker-compose*.yml"]
    assert all(r.owners == ["team-infra"] and r.status == "generated" for r in parsed.rules)


@pytest.mark.parametrize(
    "rules_yaml,needle",
    [
        ("rules:\n  - match: []\n    owners: [team-b]\n", "non-empty list of strings"),
        ("rules:\n  - match: ['ok', '']\n    owners: [team-b]\n", "each 'match' pattern must be a non-empty string"),
        ("rules:\n  - match: ['ok', 123]\n    owners: [team-b]\n", "each 'match' pattern must be a non-empty string"),
        ("rules:\n  - match: ['ok', 'a***b']\n    owners: [team-b]\n", "invalid match pattern 'a***b'"),
    ],
)
def test_multi_match_validation_errors_drop_the_rule(tmp_path: Path, rules_yaml: str, needle: str) -> None:
    # A malformed element anywhere in a list `match:` is a schema error that drops the
    # whole rule, leaving the file usable (never a rule the resolver could crash on).
    text = "version: 1\nowners: [team-a]\n" + rules_yaml
    parsed, errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert any(needle in e for e in errors)
    assert parsed is not None and parsed.rules == []


def test_multi_match_rule_wins_and_loses_under_last_match(tmp_path: Path) -> None:
    # The exploded patterns take part in last-match-wins like any rule: the later
    # multi-match rule overrides the earlier `*.yml` for its patterns only.
    _write(
        tmp_path,
        "owners.yaml",
        "version: 1\nowners: [team-a]\n"
        "rules:\n  - match: '*.yml'\n    owners: [team-yaml]\n"
        "  - match: [Dockerfile, 'docker-compose*.yml']\n    owners: [team-infra]\n",
    )
    resolver = OwnersResolver(repo_root=tmp_path)
    assert resolver.resolve("Dockerfile").owners == ["team-infra"]
    assert resolver.resolve("docker-compose.dev.yml").owners == ["team-infra"]  # beats earlier *.yml
    assert resolver.resolve("other.yml").owners == ["team-yaml"]  # only *.yml matches
    assert resolver.resolve("main.py").owners == ["team-a"]  # no rule matches


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
        ("posthog/x.py", "#team-a"),
        ("posthog/sub/y.py", "#team-b"),
        ("posthog/noinherit/z.py", "#team-c"),
        ("products/foo/thing.py", "#team-foo"),
    ],
)
def test_resolver_slack_derivation_and_fallthrough(resolver_repo: Path, path: str, slack: str) -> None:
    assert OwnersResolver(repo_root=resolver_repo).resolve(path).slack == slack


@pytest.fixture
def registry_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "owners.yaml",
        "version: 1\nowners: []\nteams:\n"
        "  team-registry:\n    slack: '#registry-chan'\n"
        "  team-silent:\n    slack: false\n",
    )
    _write(tmp_path, "reg/owners.yaml", "version: 1\nowners: [team-registry]\n")
    _write(tmp_path, "silent/owners.yaml", "version: 1\nowners: [team-silent]\n")
    _write(tmp_path, "derive/owners.yaml", "version: 1\nowners: [team-nonreg]\n")
    _write(tmp_path, "indiv/owners.yaml", "version: 1\nowners: ['@alice', team-registry]\n")
    return tmp_path


@pytest.mark.parametrize(
    "path,slack",
    [
        ("reg/x.py", "#registry-chan"),  # registry hit for the primary owner beats derived
        ("silent/x.py", None),  # registry false suppresses derivation
        ("derive/x.py", "#team-nonreg"),  # no registry entry: derive #<primary owner>
        ("indiv/x.py", None),  # primary owner is an @handle: registry ignored, no derive
    ],
)
def test_slack_registry_precedence(registry_repo: Path, path: str, slack: str | None) -> None:
    assert OwnersResolver(repo_root=registry_repo).resolve(path).slack == slack


def test_teams_registry_is_root_only(tmp_path: Path) -> None:
    text = "version: 1\nowners: [team-a]\nteams:\n  team-a:\n    slack: '#a'\n"
    _, sub_errors = parse_owners_file(text, path=tmp_path / "sub/owners.yaml", directory="sub")
    assert any("only allowed in the repo-root" in e for e in sub_errors)
    root, root_errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert root_errors == []
    assert root is not None and root.teams == {"team-a": "#a"}


@pytest.mark.parametrize(
    "teams_yaml,needle",
    [
        ("teams: [team-a]\n", "'teams' must be a mapping"),
        ("teams:\n  team-a:\n    slack: 'no-hash'\n", "must be a string starting with '#' or false"),
        ("teams:\n  team-a:\n    channel: '#a'\n", "unknown field 'channel'"),
        ("teams:\n  team-a: '#a'\n", "entry must be a mapping"),
        ("teams:\n  '@alice':\n    slack: '#a'\n", "not @handles"),
        ("teams:\n  123:\n    slack: '#a'\n", "slug must be a string"),
    ],
)
def test_teams_registry_invalid_shapes(tmp_path: Path, teams_yaml: str, needle: str) -> None:
    text = "version: 1\nowners: []\n" + teams_yaml
    file, errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert any(needle in e for e in errors)
    assert file is not None  # a bad registry entry doesn't make the file unusable


def test_teams_registry_pins_file_as_non_simple(tmp_path: Path) -> None:
    text = "version: 1\nowners: [team-a]\nteams:\n  team-a:\n    slack: '#a'\n"
    file, _ = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert file is not None
    assert is_simple_owners_file(file) is False
    assert is_simple_owners_file(file, allow_anchored_rules=True) is False


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


def _fmt_plan(tmp_path: Path, files: dict[str, str]) -> CanonicalPlan:
    for rel, text in files.items():
        _write(tmp_path, rel, text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return CanonicalPlacer(OwnersResolver(repo_root=tmp_path)).build()


def test_fmt_folds_dedicated_child_into_pinned_parent(tmp_path: Path) -> None:
    # `a` is a pinned carrier (non-simple, carries a status); `a/b` is a dedicated
    # single-statement file. Canonical folds b's statement into a and drops the file.
    plan = _fmt_plan(
        tmp_path,
        {
            "a/owners.yaml": "version: 1\nowners: [team-a]\nstatus: deprecated\n",
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
        "P/owners.yaml": "version: 1\nowners: [team-p]\nstatus: deprecated\n",
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
        "P/owners.yaml": "version: 1\nowners: [team-p]\nstatus: deprecated\n",
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


def test_fmt_reports_top_level_owner_edits(tmp_path: Path) -> None:
    # Canonical placement here rewrites the root file's `owners:` ([] -> [team-a])
    # while deleting both children. A plan that only printed the deletions would
    # under-apply: following it literally leaves every file unowned even though
    # the proof passed against the full in-memory proposal.
    plan = _fmt_plan(
        tmp_path,
        {
            "owners.yaml": "version: 1\nowners: []\n",
            "a/owners.yaml": "version: 1\nowners: [team-a]\n",
            "b/owners.yaml": "version: 1\nowners: [team-a]\n",
            "a/f.py": "x",
            "b/g.py": "x",
        },
    )
    assert not plan.is_canonical
    assert sorted(plan.deletions) == ["a/owners.yaml", "b/owners.yaml"]
    assert any("owners: [] -> [team-a]" in line for line in plan.additions.get("owners.yaml", []))


def test_fmt_reports_rule_owner_changes(tmp_path: Path) -> None:
    # The carrier already holds a `/a/` rule with stale owners; canonical placement
    # keeps the match but flips the owners. A diff that only checks for new match
    # strings would print nothing but the deletion, and applying that literally
    # would route a/** to the stale team.
    plan = _fmt_plan(
        tmp_path,
        {
            "owners.yaml": "version: 1\nowners: []\nrules:\n  - match: '/a/'\n    owners: [team-old]\n",
            "a/owners.yaml": "version: 1\nowners: [team-new]\n",
            "a/f.py": "x",
            "r1.py": "x",
        },
    )
    assert "a/owners.yaml" in plan.deletions
    assert "/a/: [team-old] -> [team-new]" in plan.additions.get("owners.yaml", [])


def test_fmt_preserves_unowned_by_design_exemptions(tmp_path: Path) -> None:
    # An `owners: null` child under a no-contribution parent must survive as an
    # explicit statement — collapsing it into plain unowned would delete the file
    # with no replacement and silently drop the coverage exemption.
    plan = _fmt_plan(
        tmp_path,
        {
            "owners.yaml": "version: 1\nowners: []\n",
            "a/owners.yaml": "version: 1\nowners: null\n",
            "a/f.py": "x",
            "r1.py": "x",
        },
    )
    if "a/owners.yaml" in plan.deletions:
        assert "/a/ -> (unowned)" in plan.additions.get("owners.yaml", [])


def test_fmt_reports_stale_rule_removals(tmp_path: Path) -> None:
    # `/b/` restates what the file's own owners already provide; canonical layout
    # drops it. The product.yaml alias above blocks carry-up, so the backend file
    # must stay open — a plan that stayed silent about the shed rule would report
    # is_canonical while the stale rule (and the cost difference) persists.
    plan = _fmt_plan(
        tmp_path,
        {
            "owners.yaml": "version: 1\nowners: []\n",
            "products/foo/product.yaml": "name: Foo\nowners:\n    - team-p\n",
            "products/foo/x.py": "x",
            "products/foo/backend/owners.yaml": (
                "version: 1\nowners: [team-a]\nrules:\n  - match: '/b/'\n    owners: [team-a]\n"
            ),
            "products/foo/backend/b/f.py": "x",
            "products/foo/backend/g.py": "x",
            "r1.py": "x",
        },
    )
    assert not plan.is_canonical
    assert "drop /b/ (was [team-a])" in plan.additions.get("products/foo/backend/owners.yaml", [])
    assert "products/foo/backend/owners.yaml" not in plan.deletions


def test_fmt_frozen_file_blocks_carry_up(tmp_path: Path) -> None:
    # d's glob file is frozen; d/sub's boundary must not be carried above d, or
    # the untouched nearer file would shadow the ancestor rule and the proof
    # would fail — this layout used to crash build() with a proof AssertionError.
    plan = _fmt_plan(
        tmp_path,
        {
            "owners.yaml": "version: 1\nowners: []\n",
            "d/owners.yaml": "version: 1\nowners: [team-d]\nrules:\n  - match: '*.py'\n    owners: [team-d]\n",
            "d/sub/owners.yaml": "version: 1\nowners: [team-s]\n",
            "d/sub/f.py": "x",
            "d/g.py": "x",
            "r1.py": "x",
        },
    )
    assert "d/sub/owners.yaml" not in plan.deletions


def test_fmt_proof_rejects_plans_that_drop_status(tmp_path: Path) -> None:
    # Folding the child appends an owner-only '/gen/' rule after the parent's
    # status-only '/gen/' rule; last-match-wins then loses `generated` while
    # owners stay identical. The proof must refuse such a plan, not print it.
    with pytest.raises(AssertionError, match="fmt bug"):
        _fmt_plan(
            tmp_path,
            {
                "owners.yaml": "version: 1\nowners: []\n",
                "a/owners.yaml": ("version: 1\nowners: [team-a]\nrules:\n  - match: '/gen/'\n    status: generated\n"),
                "a/gen/owners.yaml": "version: 1\nowners: [team-g]\n",
                "a/gen/f.py": "x",
                "a/f.py": "x",
                "r1.py": "x",
            },
        )


def test_fmt_pins_files_with_rule_level_metadata(tmp_path: Path) -> None:
    # Relocation only preserves match+owners, so a rule carrying status/inherit
    # must pin its file exactly like a glob does — otherwise folding this child
    # into the parent would silently drop the generated status.
    plan = _fmt_plan(
        tmp_path,
        {
            "a/owners.yaml": "version: 1\nowners: [team-a]\nstatus: deprecated\n",
            "a/f.py": "x",
            "a/b/owners.yaml": (
                "version: 1\nowners: [team-b]\nrules:\n  - match: '/gen/'\n    owners: [team-b]\n    status: generated\n"
            ),
            "a/b/gen/g.py": "x",
            "r1.py": "x",
            "r2.py": "x",
        },
    )
    assert plan.is_canonical


def test_fmt_is_idempotent_on_canonical_layout(tmp_path: Path) -> None:
    # A layout already in canonical form (child folded into the pinned parent) yields
    # no proposed moves.
    plan = _fmt_plan(
        tmp_path,
        {
            "a/owners.yaml": "version: 1\nowners: [team-a]\nstatus: deprecated\n"
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
