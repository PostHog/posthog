from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands.owners.conversion import Converter, parse_soft_file, render_owners_yaml
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


def test_legacy_owners_unions_matching_rules(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".github/CODEOWNERS-soft",
        "posthog/x/ @PostHog/team-a\nposthog/x/y.py @PostHog/team-b\nproducts/foo/** @rafael @PostHog/team-foo\n",
    )
    _write(tmp_path, "products/foo/product.yaml", "name: Foo\nowners:\n  - team-foo\n  - '@handle'\n")
    _write(tmp_path, "products/bar/product.yaml", "name: Bar\nowners:\n  - team-CHANGEME\n")
    legacy = LegacyOwners(tmp_path)

    assert legacy.owners_of("posthog/x/y.py") == {"team-a", "team-b"}
    assert legacy.owners_of("products/foo/z.py") == {"@rafael", "team-foo"}
    assert legacy.owners_of("products/bar/z.py") == set()
