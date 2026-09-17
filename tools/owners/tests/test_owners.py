from __future__ import annotations

import sys
import json
import subprocess
from pathlib import Path

import pytest

from click.testing import CliRunner
from owners_yaml import (
    census,
    first_team_owner,
    fmt as fmt_module,
    owner_handle,
    package_dirs_from,
    project,
    runner_for_path,
    spellings,
)
from owners_yaml.cli import _consolidation_suggestions, _live_scope, _reserved_location_error, main
from owners_yaml.fmt import CanonicalPlacer, CanonicalPlan
from owners_yaml.resolver import OwnersResolver, team_channel
from owners_yaml.schema import TOP_LEVEL_KEYS, CodeownersSettings, TeamEntry, is_simple_owners_file, parse_owners_file


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


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


def test_resolver_no_contribution_is_unowned_not_exempt(tmp_path: Path) -> None:
    _write(tmp_path, "posthog/owners.yaml", "version: 1\nowners: [team-a]\n")
    resolver = OwnersResolver(repo_root=tmp_path)
    r = resolver.resolve("other/file.py")
    assert r.owners is None
    assert r.unowned_by_design is False
    assert resolver.unowned(["other/file.py", "posthog/x.py"]) == ["other/file.py"]


@pytest.fixture
def registry_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "owners.yaml",
        "version: 1\nowners: []\nteams:\n"
        "  team-registry:\n    slack: '#registry-chan'\n"
        "  team-silent:\n    slack: false\n"
        "  team-split:\n    slack: '#split-people'\n    notifications: '#split-bots'\n",
    )
    _write(tmp_path, "reg/owners.yaml", "version: 1\nowners: [team-registry]\n")
    _write(tmp_path, "silent/owners.yaml", "version: 1\nowners: [team-silent]\n")
    _write(tmp_path, "derive/owners.yaml", "version: 1\nowners: [team-nonreg]\n")
    _write(tmp_path, "indiv/owners.yaml", "version: 1\nowners: ['@alice', team-registry]\n")
    _write(tmp_path, "split/owners.yaml", "version: 1\nowners: [team-split]\n")
    return tmp_path


def test_teams_registry_and_settings_are_root_only(tmp_path: Path) -> None:
    text = (
        "version: 1\nowners: [team-a]\ngithub_org: acme\nproducers: [bot]\n"
        "reserved_dirs: ['gen/**']\ncodeowners:\n  jest_root: web\n"
        "teams:\n  team-a:\n    slack: '#a'\n"
    )
    _, sub_errors = parse_owners_file(text, path=tmp_path / "sub/owners.yaml", directory="sub")
    assert sorted(e.split("'")[1] for e in sub_errors if "only allowed in the repo-root" in e) == [
        "codeowners",
        "github_org",
        "producers",
        "reserved_dirs",
        "teams",
    ]
    root, root_errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert root_errors == []
    assert root is not None and root.teams == {"team-a": TeamEntry(slack="#a")}
    assert root.settings.github_org == "acme"
    assert root.settings.producers == frozenset({"bot"})
    assert root.settings.reserved_dirs == ("gen/**",)
    assert root.settings.codeowners == CodeownersSettings(jest_root="web")


def test_json_schema_accepts_the_same_top_level_keys_as_the_parser() -> None:
    schema = json.loads((Path(__file__).parent.parent / "owners.schema.json").read_text())
    assert set(schema["properties"]) == TOP_LEVEL_KEYS


@pytest.mark.parametrize(
    "settings_yaml,needle",
    [
        ("github_org: acme/repo\n", "'github_org' must be a GitHub organization name"),
        ("producers: bot\n", "'producers' must be a list"),
        ("reserved_dirs: ['a***b']\n", "reserved_dirs: invalid pattern"),
        ("codeowners:\n  jest_dir: web\n", "codeowners: unknown field 'jest_dir'"),
    ],
)
def test_invalid_repo_settings_are_schema_errors(tmp_path: Path, settings_yaml: str, needle: str) -> None:
    file, errors = parse_owners_file(
        "version: 1\nowners: []\n" + settings_yaml, path=tmp_path / "owners.yaml", directory=""
    )
    assert any(needle in e for e in errors), errors
    assert file is not None


@pytest.mark.parametrize(
    "teams_yaml,needle",
    [
        ("teams: [team-a]\n", "'teams' must be a mapping"),
        ("teams:\n  team-a:\n    slack: 'no-hash'\n", "must be a string starting with '#' or false"),
        ("teams:\n  team-a:\n    notifications: 'no-hash'\n", "must be a string starting with '#' or false"),
        ("teams:\n  team-a:\n    channel: '#a'\n", "unknown field 'channel'"),
        ("teams:\n  team-a: '#a'\n", "entry must be a mapping"),
        ("teams:\n  '@alice':\n    slack: '#a'\n", "not @handles"),
        ("teams:\n  123:\n    slack: '#a'\n", "slug must be a string"),
        ("teams:\n  team-a:\n    slack:\n      stamphog: false\n", "takes a single channel"),
        ("teams:\n  team-a:\n    notifications:\n      nosuchbot: false\n", "unknown producer 'nosuchbot'"),
        ("teams:\n  team-a:\n    notifications:\n      stamphog: 'no-hash'\n", "'stamphog' must be a string"),
        ("teams:\n  team-a:\n    notifications:\n      visual_review: 'no-hash'\n", "'visual_review' must be a string"),
        ("teams:\n  team-a:\n    notifications: {}\n", "mapping names no producer"),
    ],
)
def test_teams_registry_invalid_shapes(tmp_path: Path, teams_yaml: str, needle: str) -> None:
    text = "version: 1\nowners: []\nproducers: [stamphog, visual_review]\n" + teams_yaml
    file, errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert any(needle in e for e in errors)
    assert file is not None  # a bad registry entry doesn't make the file unusable


@pytest.mark.parametrize(
    "entry,purpose,channel,declared",
    [
        (TeamEntry(slack="#team-a"), "slack", "#team-a", True),
        # A team that never separates the two keeps one entry, and automation follows the people.
        (TeamEntry(slack="#team-a"), "notifications", "#team-a", True),
        (TeamEntry(slack="#team-a", notifications="#bots-a"), "notifications", "#bots-a", True),
        # Silencing automation must not read as "this team has no channel": people still have one.
        (TeamEntry(slack="#team-a", notifications=False), "notifications", None, True),
        (TeamEntry(slack="#team-a", notifications=False), "slack", "#team-a", True),
        # Declaring only the automation channel leaves the people lookup on the derived name.
        (TeamEntry(notifications="#bots-a"), "slack", "#team-a", False),
        (TeamEntry(slack=False), "notifications", None, True),
    ],
)
def test_team_channel_falls_back_by_purpose(
    entry: TeamEntry, purpose: str, channel: str | None, declared: bool
) -> None:
    # The fallback is what lets one entry serve both readers. Losing it would route every digest to
    # a derived #<slug> that may not exist, and conflating a silenced automation channel with a
    # team that has no channel at all would take the people channel down with it.
    resolved = team_channel("team-a", {"team-a": entry}, purpose)
    assert (resolved.channel, resolved.declared) == (channel, declared)


@pytest.mark.parametrize(
    "notifications,producer,channel,declared",
    [
        # Silencing one producer leaves every other reader on the people channel, which is the
        # whole point of the per-producer form over `notifications: false`.
        ({"stamphog": False}, "stamphog", None, True),
        ({"stamphog": False}, None, "#team-a", True),
        ({"stamphog": "#bots-a"}, "stamphog", "#bots-a", True),
        # A scalar answers every producer, so naming one must not move the channel.
        ("#bots-a", "stamphog", "#bots-a", True),
        (False, "stamphog", None, True),
    ],
)
def test_team_channel_resolves_per_producer(
    notifications: str | bool | dict[str, str | bool], producer: str | None, channel: str | None, declared: bool
) -> None:
    entry = TeamEntry(slack="#team-a", notifications=notifications)
    resolved = team_channel("team-a", {"team-a": entry}, "notifications", producer)
    assert (resolved.channel, resolved.declared) == (channel, declared)


def test_team_channel_derives_for_an_unregistered_slug() -> None:
    assert team_channel("team-b", {"team-a": TeamEntry(slack="#a")}, "notifications") == team_channel(
        "team-b", {}, "notifications"
    )


def test_an_unreadable_producer_map_registers_as_silence(tmp_path: Path) -> None:
    # Dropping the key instead would fall through to the derived channel, so a typo in a repo our
    # lint never reads would post the digest the team asked to be left out of.
    text = (
        "version: 1\nowners: []\nproducers: [stamphog]\nteams:\n  team-a:\n    notifications:\n      stamphogg: false\n"
    )
    file, errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert any("unknown producer" in e for e in errors)
    assert file is not None and file.teams == {"team-a": TeamEntry(notifications=False)}


def test_a_repo_without_a_producers_list_accepts_any_producer(tmp_path: Path) -> None:
    text = "version: 1\nowners: []\nteams:\n  team-a:\n    notifications:\n      reviewbot: '#a-bots'\n"
    file, errors = parse_owners_file(text, path=tmp_path / "owners.yaml", directory="")
    assert errors == []
    assert file is not None and file.teams == {"team-a": TeamEntry(notifications={"reviewbot": "#a-bots"})}


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
    assert (_reserved_location_error(rel, ("products/**/mcp/**",)) is not None) is reserved


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


def test_fmt_keeps_a_nested_carrier_from_claiming_its_glob_served_parent(tmp_path: Path) -> None:
    # `d` is frozen by its `ml-*` glob, so only `costs` is left to vote up the chain. A
    # dir-statement built from that vote sits nearer than `d/owners.yaml`, shadows it,
    # and moves `d/sub/a.py` off team-a, which the proof catches by aborting.
    plan = _fmt_plan(
        tmp_path,
        {
            "owners.yaml": "version: 1\nowners: [team-root]\n",
            "r1.py": "x",
            "r2.py": "x",
            "d/owners.yaml": (
                "version: 1\nowners: []\nrules:\n"
                "  - match: '/sub/'\n    owners: [team-a]\n"
                "  - match: '/sub/ml-*/'\n    owners: [team-c]\n"
            ),
            "d/sub/ml-one/z.py": "x",
            "d/sub/a.py": "x",
            "d/sub/b.py": "x",
            "d/sub/pipe/ai/costs/owners.yaml": "version: 1\nowners: [team-b]\n",
            "d/sub/pipe/ai/costs/g.py": "x",
            "d/sub/pipe/ai/costs/h.py": "x",
        },
    )
    assert plan.creations == []
    assert plan.deletions == []


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


_OWNERS_BY_FILE = {
    "owners.yaml": {"team-devex", "team-billing"},
    "rust/owners.yaml": {"ai-research"},
    "ee/owners.yaml": {"team-bogus"},
}


@pytest.mark.parametrize(
    "paths,expected",
    [
        ((), {"team-devex", "team-billing", "ai-research", "team-bogus"}),
        (("rust/owners.yaml",), {"ai-research"}),
        (("owners.yaml", "rust/owners.yaml"), {"team-devex", "team-billing", "ai-research"}),
        (("./rust/owners.yaml",), {"ai-research"}),
        (("posthog/owners.yaml",), set()),
    ],
)
def test_live_scope_limits_validation_to_the_given_files(paths: tuple[str, ...], expected: set[str]) -> None:
    assert _live_scope(_OWNERS_BY_FILE, paths) == expected


def test_live_scope_ignores_stale_owners_outside_the_diff() -> None:
    assert "team-bogus" not in _live_scope(_OWNERS_BY_FILE, ("owners.yaml",))


def test_resolver_reads_through_an_injected_source() -> None:
    files = {
        "owners.yaml": "version: 1\nowners: [team-root]\n",
        "posthog/temporal/owners.yaml": "version: 1\nowners: [team-batch]\n",
    }

    class DictSource:
        def read(self, path: str) -> str | None:
            return files.get(path)

    resolver = OwnersResolver(source=DictSource())
    assert resolver.resolve("posthog/temporal/test_run.py").owners == ["team-batch"]
    assert resolver.resolve("posthog/other.py").owners == ["team-root"]
    assert resolver.resolve("posthog/temporal/test_run.py").source == "posthog/temporal/owners.yaml"


def test_map_prefetches_a_batch_through_read_all_before_any_read() -> None:
    calls: list[tuple[str, object]] = []

    class BatchDictSource:
        def read(self, path: str) -> str | None:
            calls.append(("read", path))
            return "version: 1\nowners: [team-root]\n" if path == "owners.yaml" else None

        def read_all(self, paths: list[str]) -> None:
            calls.append(("read_all", list(paths)))

    resolver = OwnersResolver(source=BatchDictSource())
    resolver.map(["a/b/x.py"])

    assert calls[0] == (
        "read_all",
        [
            "a/b/owners.yaml",
            "a/b/product.yaml",
            "a/owners.yaml",
            "a/product.yaml",
            "owners.yaml",
            "product.yaml",
        ],
    )
    assert all(c[0] == "read" for c in calls[1:])


def test_census_counts_test_files_per_team_and_folds_gaps_into_unowned(tmp_path: Path) -> None:
    _write(tmp_path, "owners.yaml", "version: 1\nowners: []\n")
    _write(tmp_path, "products/a/owners.yaml", "version: 1\nowners: [team-a]\n")
    _write(tmp_path, "products/p/owners.yaml", "version: 1\nowners: ['@someone']\n")
    paths = [
        "products/a/backend/test_api.py",
        "products/a/backend/queries_test.py",
        "products/a/frontend/thing.test.tsx",
        "products/a/frontend/thing.tsx",
        "products/p/backend/test_personal.py",
        "posthog/test_uncovered.py",
    ]

    result = census(paths, tmp_path)

    assert [(c.owner_team, c.pytest_file_count, c.jest_file_count) for c in result] == [
        ("team-a", 2, 1),
        ("unowned", 2, 0),
    ]


def test_first_team_owner_skips_handles() -> None:
    assert first_team_owner(["@someone", "team-a"]) == "team-a"
    assert first_team_owner(["@someone"]) == ""
    assert first_team_owner(None) == ""


def _run_entrypoint(repo: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "owners_yaml", *args],
        cwd=repo,
        input=stdin,
        capture_output=True,
        text=True,
    )


def test_json_entrypoint_resolves_against_an_explicit_repo_root(registry_repo: Path) -> None:
    # The fixture must have no .git, or the git rev-parse default could answer instead of the flag.
    assert not (registry_repo / ".git").exists()

    result = _run_entrypoint(registry_repo, "--repo-root", str(registry_repo), "reg/x.py")

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response == {
        "reg/x.py": {
            "owners": ["team-registry"],
            "status": "active",
            "slack": "#registry-chan",
            "source": "reg/owners.yaml",
        }
    }
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).parent.parent / "resolution.schema.json").read_text())
    jsonschema.validate(response, schema)


def test_json_entrypoint_repo_root_reads_stdin_paths_and_honors_purpose(registry_repo: Path) -> None:
    result = _run_entrypoint(
        registry_repo,
        "--repo-root",
        str(registry_repo),
        "--purpose",
        "notifications",
        stdin="split/x.py\nderive/x.py\n",
    )

    assert result.returncode == 0, result.stderr
    wire = json.loads(result.stdout)
    assert wire["split/x.py"]["slack"] == "#split-bots"
    assert wire["derive/x.py"]["slack"] == "#team-nonreg"


@pytest.mark.parametrize("root", ["nope", ""], ids=["missing", "empty"])
def test_json_entrypoint_rejects_a_repo_root_that_is_not_a_directory(registry_repo: Path, root: str) -> None:
    # An empty root is the unset "$VAR" case: Path("") is Path("."), which would
    # otherwise resolve against the working directory rather than fail.
    result = _run_entrypoint(registry_repo, "--repo-root", str(registry_repo / root) if root else "", "reg/x.py")

    assert result.returncode == 2
    assert "--repo-root" in result.stderr
    assert result.stdout == ""


def _codeowners_lookup(rendered: str, path: str) -> list[str]:
    # The projection emits two rule shapes only: an exact file path, and a directory prefix ending
    # in "/". Last match wins, which is what CODEOWNERS consumers implement.
    owners: list[str] = []
    for line in rendered.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, *rule_owners = line.split()
        pattern = pattern.lstrip("/")
        if pattern.endswith("/") and path.startswith(pattern):
            owners = rule_owners
        elif path == pattern:
            owners = rule_owners
    return owners


@pytest.fixture
def projection_repo(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "owners.yaml",
        "version: 1\nowners: []\ngithub_org: PostHog\n",
    )
    _write(tmp_path, "posthog/security/owners.yaml", "version: 1\nowners: [team-security]\n")
    _write(tmp_path, "posthog/security/test/owners.yaml", "version: 1\nowners: null\n")
    _write(tmp_path, "products/alpha/owners.yaml", "version: 1\nowners: [team-alpha, '@someone']\n")
    _write(tmp_path, "products/beta/owners.yaml", "version: 1\nowners: [team-beta]\n")
    _write(tmp_path, "frontend/owners.yaml", "version: 1\nowners: [team-web]\n")
    _write(tmp_path, "nodejs/owners.yaml", "version: 1\nowners: [team-pipeline]\n")
    return tmp_path


JEST_ROOT_SETTINGS = CodeownersSettings(
    jest_root="frontend", jest_root_tests="products/**/frontend/**", jest_root_packages="products"
)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("posthog/api/test_thing.py", ["posthog/api/test_thing.py"]),
        ("frontend/src/a.test.tsx", ["frontend/src/a.test.tsx", "src/a.test.tsx"]),
        (
            "products/alpha/frontend/a.test.tsx",
            ["products/alpha/frontend/a.test.tsx", "../products/alpha/frontend/a.test.tsx"],
        ),
    ],
    ids=["pytest-runs-from-the-repo-root", "jest-runs-from-its-package", "product-frontends-run-from-frontend"],
)
def test_spellings_cover_how_each_runner_writes_the_file_attribute(path: str, expected: list[str]) -> None:
    package_dirs = package_dirs_from(["frontend/package.json", "products/alpha/package.json"])
    assert spellings(path, package_dirs, JEST_ROOT_SETTINGS) == expected


def test_projection_resolves_every_spelling_to_what_the_resolver_says(projection_repo: Path) -> None:
    tracked = [
        "frontend/package.json",
        "products/alpha/package.json",
        "frontend/src/a.test.tsx",
        "posthog/security/test_sanitization.py",
        "posthog/security/test/test_proxy.py",
        "products/alpha/frontend/widget.test.tsx",
        "products/alpha/backend/test_api.py",
        "products/beta/backend/test_api.py",
        "products/beta/backend/api.py",
    ]
    resolver = OwnersResolver(projection_repo)

    projection = project(
        tracked, resolver, org="PostHog", package_dirs=package_dirs_from(tracked), settings=JEST_ROOT_SETTINGS
    )
    rendered = projection.render()

    for path in tracked:
        if runner_for_path(path) is None:
            continue
        expected = [owner_handle(owner, "PostHog") for owner in resolver.resolve(path).owners or []]
        for spelling in spellings(path, package_dirs_from(tracked), JEST_ROOT_SETTINGS):
            assert _codeowners_lookup(rendered, spelling) == expected, f"{spelling} resolved wrongly"
    assert projection.owned_file_count == 5
    assert projection.unowned_file_count == 1


def test_projection_drops_a_spelling_two_teams_would_both_claim(projection_repo: Path) -> None:
    tracked = [
        "frontend/package.json",
        "nodejs/package.json",
        "frontend/src/shared.test.ts",
        "nodejs/src/shared.test.ts",
        # A sibling that leaves one owner in the directory, so a rule for the directory would
        # otherwise claim the ambiguous spelling next to it.
        "frontend/src/solo.test.ts",
    ]

    projection = project(
        tracked, OwnersResolver(projection_repo), org="PostHog", package_dirs=package_dirs_from(tracked)
    )
    rendered = projection.render()

    assert projection.ambiguous_spellings == ["src/shared.test.ts"]
    assert _codeowners_lookup(rendered, "src/shared.test.ts") == []
    assert _codeowners_lookup(rendered, "src/solo.test.ts") == ["@PostHog/team-web"]
    assert _codeowners_lookup(rendered, "frontend/src/shared.test.ts") == ["@PostHog/team-web"]
    assert _codeowners_lookup(rendered, "nodejs/src/shared.test.ts") == ["@PostHog/team-pipeline"]


def test_cli_lints_a_tree_that_is_not_a_git_worktree(registry_repo: Path) -> None:
    _write(registry_repo, "reg/code.py", "")
    _write(registry_repo, "loose/code.py", "")

    result = CliRunner().invoke(main, ["lint", "--repo-root", str(registry_repo)])

    assert result.exit_code == 0, result.output
    # The walk finds the six ownership files plus the two code files, and only loose/code.py is unowned.
    assert "coverage: 2 of 8 tracked file(s) resolve to unowned" in result.output


@pytest.mark.parametrize(
    "args,message",
    [
        (["lint"], "not inside a git worktree"),
        (["codeowners", "--repo-root", "."], "no GitHub organization"),
        (["lint", "--live", "--repo-root", "."], "no GitHub organization"),
    ],
    ids=["no-repo-root", "codeowners-without-org", "live-lint-without-org"],
)
def test_cli_reports_missing_context_without_a_traceback(tmp_path: Path, args: list[str], message: str) -> None:
    _write(tmp_path, "owners.yaml", "version: 1\nowners: [team-a]\n")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        _write(Path(cwd), "owners.yaml", "version: 1\nowners: [team-a]\n")
        result = runner.invoke(main, args)

    assert result.exit_code == 1
    assert message in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
