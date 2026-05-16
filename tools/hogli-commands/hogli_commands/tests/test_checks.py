"""Tests for product lint checks — focused on PackageJsonScriptsCheck."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hogli_commands.product import gh as gh_module
from hogli_commands.product.checks import (
    CheckContext,
    FileFolderConflictsCheck,
    PackageJsonScriptsCheck,
    ProductYamlCheck,
    ProductYamlOwnersCheck,
    _has_test_files,
    _is_noop_script,
    _names_from_pattern,
    _parse_pytest_paths,
    has_legacy_interface_leaks,
    validate_facade_alternation,
    validate_interface_blocks,
    validate_tach_references,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(
    tmp_path: Path,
    *,
    scripts: dict[str, str] | None = None,
    has_backend: bool = True,
    isolated: bool = False,
    test_files: list[str] | None = None,
    extra_dirs: list[str] | None = None,
) -> CheckContext:
    """Build a minimal product directory and return a CheckContext for it."""
    product_dir = tmp_path / "my_product"
    product_dir.mkdir()
    backend_dir = product_dir / "backend"

    if has_backend:
        backend_dir.mkdir()

    if isolated:
        (backend_dir / "facade").mkdir(parents=True, exist_ok=True)
        (backend_dir / "facade" / "contracts.py").write_text("")
        (backend_dir / "facade" / "api.py").write_text("def get_thing():\n    pass\n")

    if scripts is not None:
        (product_dir / "package.json").write_text(json.dumps({"scripts": scripts}))

    if test_files:
        for tf in test_files:
            p = backend_dir / tf
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")

    if extra_dirs:
        for d in extra_dirs:
            (product_dir / d).mkdir(parents=True, exist_ok=True)

    return CheckContext(
        name="my_product",
        product_dir=product_dir,
        backend_dir=backend_dir,
        is_isolated=isolated,
        structure={},
        detailed=False,
    )


check = PackageJsonScriptsCheck()


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestParseHelpers:
    @pytest.mark.parametrize(
        "script, expected",
        [
            ("pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short", ["backend/tests"]),
            ("pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short", ["backend/"]),
            (
                "pytest -c ../../pytest.ini --rootdir ../.. backend/ stats/tests -v --tb=short",
                ["backend/", "stats/tests"],
            ),
            ("pytest backend/test_max_tools.py", ["backend/test_max_tools.py"]),
            ("echo 'No backend tests'", []),
            ("pytest -v", []),
            ("pytest -c ../../pytest.ini --rootdir ../.. -k 'not slow' backend/tests", ["backend/tests"]),
        ],
    )
    def test_parse_pytest_paths(self, script: str, expected: list[str]) -> None:
        assert _parse_pytest_paths(script) == expected

    @pytest.mark.parametrize(
        "script, expected",
        [
            ("echo 'No backend tests'", True),
            ("echo skip", True),
            ("true", True),
            ("exit 0", True),
            (":", True),
            ("pytest backend/tests", False),
            ("pytest -v", False),
        ],
    )
    def test_is_noop_script(self, script: str, expected: bool) -> None:
        assert _is_noop_script(script) == expected

    def test_has_test_files_true(self, tmp_path: Path) -> None:
        (tmp_path / "test_foo.py").write_text("")
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_nested(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_bar.py").write_text("")
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_suffix_convention(self, tmp_path: Path) -> None:
        (tmp_path / "foo_test.py").write_text("")
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_false(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text("")
        assert _has_test_files(tmp_path) is False

    def test_has_test_files_empty_dir(self, tmp_path: Path) -> None:
        assert _has_test_files(tmp_path) is False


# ---------------------------------------------------------------------------
# Presence checks
# ---------------------------------------------------------------------------


class TestPresenceChecks:
    def test_skip_when_no_backend_dir(self, tmp_path: Path) -> None:
        ctx = _make_product(tmp_path, has_backend=False)
        result = check.run(ctx)
        assert result.skip is True

    def test_backend_test_required_when_backend_exists(self, tmp_path: Path) -> None:
        ctx = _make_product(tmp_path, scripts={})
        result = check.run(ctx)
        assert any("missing 'backend:test'" in i for i in result.issues)

    def test_backend_test_present_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues

    def test_contract_check_required_for_isolated(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            isolated=True,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert any("missing 'backend:contract-check'" in i for i in result.issues)

    def test_contract_check_present_for_isolated_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=True,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues

    def test_invalid_json_returns_issue(self, tmp_path: Path) -> None:
        ctx = _make_product(tmp_path, has_backend=True)
        (ctx.product_dir / "package.json").write_text("{invalid json")
        result = check.run(ctx)
        assert any("not valid JSON" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Absence checks
# ---------------------------------------------------------------------------


class TestAbsenceChecks:
    def test_contract_check_forbidden_for_non_isolated(self, tmp_path: Path) -> None:
        """Non-isolated product with contract-check causes turbo-discover misclassification."""
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=False,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert result.issues
        assert any("turbo-discover" in i for i in result.issues)

    def test_no_contract_check_for_non_isolated_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            isolated=False,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues


# ---------------------------------------------------------------------------
# Content checks: pytest path validation
# ---------------------------------------------------------------------------


class TestPytestPathValidation:
    def test_valid_path_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short"},
            test_files=["tests/test_foo.py"],
        )
        result = check.run(ctx)
        assert not result.issues

    def test_nonexistent_path_fails(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/typo_tests -v --tb=short"},
        )
        result = check.run(ctx)
        assert any("does not exist" in i for i in result.issues)
        assert any("typo_tests" in i for i in result.issues)

    def test_multiple_paths_one_missing(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ stats/tests -v --tb=short"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        # backend/ exists, stats/tests does not
        assert any("stats/tests" in i for i in result.issues)
        assert not any("backend/" in i for i in result.issues)

    def test_file_path_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/test_max_tools.py -v --tb=short"
            },
            test_files=["test_max_tools.py"],
        )
        result = check.run(ctx)
        assert not result.issues


# ---------------------------------------------------------------------------
# Content checks: no-op detection
# ---------------------------------------------------------------------------


class TestNoopDetection:
    def test_noop_without_test_files_passes(self, tmp_path: Path) -> None:
        """echo 'No backend tests' is fine when there are genuinely no test files."""
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "echo 'No backend tests'"},
        )
        result = check.run(ctx)
        assert not result.issues

    def test_noop_with_test_files_fails(self, tmp_path: Path) -> None:
        """echo 'No backend tests' is wrong when test files actually exist."""
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "echo 'No backend tests'"},
            test_files=["tests/test_something.py"],
        )
        result = check.run(ctx)
        assert any("no-op" in i for i in result.issues)
        assert any("test files" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Content checks: || true detection
# ---------------------------------------------------------------------------


class TestPipeTrueDetection:
    def test_pipe_true_fails(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short || true"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert any("|| true" in i for i in result.issues)
        assert any("swallows" in i for i in result.issues)

    def test_pipe_exit_0_fails(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short || exit 0"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert any("|| exit 0" in i for i in result.issues)
        assert any("swallows" in i for i in result.issues)

    def test_no_pipe_true_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues


# ---------------------------------------------------------------------------
# Combined scenario: isolated product, all good
# ---------------------------------------------------------------------------


class TestCombinedScenarios:
    def test_fully_valid_isolated_product(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=True,
            test_files=["tests/test_api.py"],
        )
        result = check.run(ctx)
        assert not result.issues
        assert any("✓ ok" in line for line in result.lines)

    def test_fully_valid_legacy_product(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            isolated=False,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues
        assert any("✓ ok" in line for line in result.lines)

    def test_multiple_issues_reported(self, tmp_path: Path) -> None:
        """A product with several problems reports all of them."""
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/nonexistent -v --tb=short || true",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=False,
        )
        result = check.run(ctx)
        # Should report: contract-check forbidden, || true, nonexistent path
        assert len(result.issues) >= 3


# ---------------------------------------------------------------------------
# has_legacy_interface_leaks
# ---------------------------------------------------------------------------

_TACH_SAMPLE = """\
[[modules]]
path = "products.visual_review"
depends_on = ["posthog"]
layer = "modules"

[[modules]]
path = "products.experiments"
depends_on = ["ee", "posthog"]
layer = "modules"

[[modules]]
path = "products.mcp_store"
depends_on = ["ee", "posthog"]
layer = "modules"

# Facade + views: canonical public surface
[[interfaces]]
expose = [
    "backend\\.facade.*",
    "backend\\.presentation\\.views.*",
]
from = [
    "products\\.(experiments|mcp_store|visual_review)",
]

# Legacy leaks — experiments
[[interfaces]]
expose = [
    "backend\\.models.*",
    "stats\\..*",
]
from = [
    "products.experiments",
]

# Legacy leaks — mcp_store
[[interfaces]]
expose = [
    "backend\\.models.*",
    "backend\\.oauth.*",
]
from = [
    "products.mcp_store",
]
"""


class TestLegacyInterfaceLeaks:
    @pytest.mark.parametrize(
        "module_path, expected",
        [
            ("products.visual_review", False),
            ("products.experiments", True),
            ("products.mcp_store", True),
            ("products.nonexistent", False),
        ],
    )
    def test_detection(self, module_path: str, expected: bool) -> None:
        assert has_legacy_interface_leaks(_TACH_SAMPLE, module_path) == expected

    def test_empty_tach(self) -> None:
        assert has_legacy_interface_leaks("", "products.anything") is False

    def test_only_facade_block(self) -> None:
        tach = """\
[[interfaces]]
expose = [
    "backend\\.facade.*",
    "backend\\.presentation\\.views.*",
]
from = [
    "products.clean_product",
]
"""
        assert has_legacy_interface_leaks(tach, "products.clean_product") is False

    def test_regex_from_does_not_false_positive(self) -> None:
        assert has_legacy_interface_leaks(_TACH_SAMPLE, "products.mcp") is False


# ---------------------------------------------------------------------------
# ProductYamlCheck
# ---------------------------------------------------------------------------

yaml_check = ProductYamlCheck()
owners_check = ProductYamlOwnersCheck()


def _make_yaml_ctx(tmp_path: Path, yaml_content: str | None = None) -> CheckContext:
    product_dir = tmp_path / "test_product"
    product_dir.mkdir()
    backend_dir = product_dir / "backend"
    backend_dir.mkdir()
    if yaml_content is not None:
        (product_dir / "product.yaml").write_text(yaml_content)
    return CheckContext(
        name="test_product",
        product_dir=product_dir,
        backend_dir=backend_dir,
        is_isolated=False,
        structure={},
        detailed=False,
    )


class TestProductYamlCheck:
    def test_missing_file(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path)
        result = yaml_check.run(ctx)
        assert any("Missing product.yaml" in i for i in result.issues)

    def test_valid_yaml(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - team-foo\n")
        result = yaml_check.run(ctx)
        assert not result.issues

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: [\ninvalid")
        result = yaml_check.run(ctx)
        assert any("invalid YAML" in i for i in result.issues)

    def test_non_dict_yaml(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "- just\n- a\n- list\n")
        result = yaml_check.run(ctx)
        assert any("must be a YAML mapping" in i for i in result.issues)

    def test_missing_name(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "owners:\n  - team-foo\n")
        result = yaml_check.run(ctx)
        assert any("missing 'name'" in i for i in result.issues)

    def test_missing_owners(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\n")
        result = yaml_check.run(ctx)
        assert any("missing 'owners'" in i for i in result.issues)

    def test_owners_must_be_list(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners: team-foo\n")
        result = yaml_check.run(ctx)
        assert any("list of strings" in i for i in result.issues)

    def test_owners_must_be_strings(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - 123\n")
        result = yaml_check.run(ctx)
        assert any("list of strings" in i for i in result.issues)

    def test_name_must_be_string(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: 42\nowners:\n  - team-foo\n")
        result = yaml_check.run(ctx)
        assert any("missing 'name'" in i for i in result.issues)


class TestProductYamlOwnersCheck:
    def test_skip_when_no_owners(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\n")
        result = owners_check.run(ctx)
        assert result.skip

    def test_skip_when_owners_wrong_type(self, tmp_path: Path) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners: team-foo\n")
        result = owners_check.run(ctx)
        assert result.skip

    def test_invalid_slug_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - team-nonexistent\n")
        monkeypatch.setattr(gh_module, "_fetch_attempted", True)
        monkeypatch.setattr(gh_module, "_team_slugs", {"team-real"})
        monkeypatch.setattr(gh_module, "_fetch_err", "")
        result = owners_check.run(ctx)
        assert any("team-nonexistent" in i for i in result.issues)

    def test_valid_slug_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - team-real\n")
        monkeypatch.setattr(gh_module, "_fetch_attempted", True)
        monkeypatch.setattr(gh_module, "_team_slugs", {"team-real"})
        monkeypatch.setattr(gh_module, "_fetch_err", "")
        result = owners_check.run(ctx)
        assert not result.issues

    def test_gh_unavailable_is_error_locally(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - team-foo\n")
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setattr(gh_module, "_fetch_attempted", True)
        monkeypatch.setattr(gh_module, "_team_slugs", None)
        monkeypatch.setattr(gh_module, "_fetch_err", "gh CLI not found")
        result = owners_check.run(ctx)
        assert result.issues
        assert any("gh CLI" in i for i in result.issues)

    def test_gh_unavailable_skips_in_ci(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - team-foo\n")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setattr(gh_module, "_fetch_attempted", True)
        monkeypatch.setattr(gh_module, "_team_slugs", None)
        monkeypatch.setattr(gh_module, "_fetch_err", "gh CLI not found")
        result = owners_check.run(ctx)
        assert not result.issues


# ---------------------------------------------------------------------------
# FileFolderConflictsCheck — file vs package twin detection
# ---------------------------------------------------------------------------

# Structure mirrors product_structure.yaml: logic is a package, models can be
# either a file or folder. Tests exercise both shapes plus a stray-twin case.
_CONFLICT_STRUCTURE = {
    "backend_files": {
        "models.py": {"can_be_folder": True},
        "logic/": {"__init__.py": {}},
        "tasks/": {"__init__.py": {}},
    },
}

conflict_check = FileFolderConflictsCheck()


def _make_backend(tmp_path: Path, files: list[str]) -> CheckContext:
    """Create a product with the given files/dirs under backend/. Trailing '/' = directory."""
    product_dir = tmp_path / "p"
    backend = product_dir / "backend"
    backend.mkdir(parents=True)
    for f in files:
        target = backend / f.rstrip("/")
        if f.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("")
    return CheckContext(
        name="p",
        product_dir=product_dir,
        backend_dir=backend,
        is_isolated=False,
        structure=_CONFLICT_STRUCTURE,
        detailed=False,
    )


class TestFileFolderConflictsCheck:
    def test_skip_when_no_backend(self, tmp_path: Path) -> None:
        product_dir = tmp_path / "p"
        product_dir.mkdir()
        ctx = CheckContext(
            name="p",
            product_dir=product_dir,
            backend_dir=product_dir / "backend",
            is_isolated=False,
            structure=_CONFLICT_STRUCTURE,
            detailed=False,
        )
        assert conflict_check.run(ctx).skip is True

    @pytest.mark.parametrize(
        "files, expect_conflicts",
        [
            # Pattern A (can_be_folder): models.py only / models/ only — both fine
            (["models.py"], []),
            (["models/"], []),
            (["models.py", "models/"], ["models.py"]),
            # Pattern B (package init): logic.py only / logic/ only — both fine
            (["logic/__init__.py"], []),
            (["logic.py"], []),
            (["logic/"], []),  # half-migrated package without __init__.py
            (["logic.py", "logic/__init__.py"], ["logic.py"]),
            (["logic.py", "logic/"], ["logic.py"]),  # __init__.py absent — still flagged
            # Pattern B also covers other canonical packages — stray tasks.py is a mistake
            (["tasks/__init__.py"], []),
            (["tasks.py", "tasks/__init__.py"], ["tasks.py"]),
            # Multiple conflicts at once
            (["logic.py", "logic/", "models.py", "models/"], ["logic.py", "models.py"]),
        ],
    )
    def test_conflict_detection(self, tmp_path: Path, files: list[str], expect_conflicts: list[str]) -> None:
        ctx = _make_backend(tmp_path, files)
        result = conflict_check.run(ctx)
        if not expect_conflicts:
            assert not result.issues, f"unexpected conflicts: {result.issues}"
            return
        assert len(result.issues) == len(expect_conflicts)
        for stem in expect_conflicts:
            assert any(f"backend/{stem}" in i and f"backend/{stem[:-3]}/" in i for i in result.issues), result.issues


# ---------------------------------------------------------------------------
# validate_facade_alternation — global tach.toml check
# ---------------------------------------------------------------------------


def _mkproduct(products_dir: Path, name: str, *, isolated: bool) -> None:
    p = products_dir / name
    (p / "backend").mkdir(parents=True)
    (p / "__init__.py").write_text("")
    (p / "backend" / "__init__.py").write_text("")
    if isolated:
        (p / "backend" / "facade").mkdir()
        (p / "backend" / "facade" / "contracts.py").write_text("")


_CANONICAL_BLOCK = """\
[[interfaces]]
expose = [
    "backend\\\\.facade.*",
    "backend\\\\.presentation\\\\.views.*",
]
from = [
    "products\\\\.(alpha|beta)",
]
"""


_LEGACY_ONLY_TACH = """\
[[interfaces]]
expose = ["backend\\\\.models.*"]
from = ["products.alpha"]
"""

# Real tach.toml on disk uses literal `\\.` (two backslashes + dot).
# `_CANONICAL_BLOCK` already encodes that form via escaped backslashes in
# the Python source — `\\\\` in source is two literal backslashes at runtime.
# This row uses a non-alternation single-name `from` so the parametrized
# test additionally exercises that branch of `_names_from_pattern`.
_CANONICAL_SINGLE_NAME_TACH = (
    "[[interfaces]]\n"
    'expose = [\n    "backend\\\\.facade.*",\n    "backend\\\\.presentation\\\\.views.*",\n]\n'
    'from = [\n    "products\\\\.alpha",\n]\n'
)


class TestValidateFacadeAlternation:
    @pytest.mark.parametrize(
        "products, tach, expected_substrings",
        [
            # Empty tach — nothing to validate.
            ([], "", []),
            # Only a legacy-leak block — TachCheck handles per-product, this
            # validator stays quiet.
            ([("alpha", True)], _LEGACY_ONLY_TACH, []),
            # Clean alternation: every listed product exists and is isolated.
            ([("alpha", True), ("beta", True)], _CANONICAL_BLOCK, []),
            # Stale entry: product listed but not on disk.
            ([("alpha", True)], _CANONICAL_BLOCK, [("beta", "does not exist")]),
            # Stale entry: product on disk but missing contracts.py.
            (
                [("alpha", True), ("beta", False)],
                _CANONICAL_BLOCK,
                [("beta", "contracts.py")],
            ),
            # On-disk single-name `from` (no alternation) parses.
            ([("alpha", True)], _CANONICAL_SINGLE_NAME_TACH, []),
            # Non-listed isolated products are tolerated — having
            # facade/contracts.py is just scaffolding, not a commitment to
            # canonical exposure.
            (
                [("alpha", True), ("beta", True), ("gamma", True)],
                _CANONICAL_BLOCK,
                [],
            ),
        ],
        ids=[
            "empty_tach",
            "legacy_only_block_silent",
            "clean_alternation",
            "stale_entry_missing_on_disk",
            "stale_entry_not_isolated",
            "on_disk_single_name_form_parses",
            "isolated_but_not_in_alternation_is_tolerated",
        ],
    )
    def test_validate(
        self,
        tmp_path: Path,
        products: list[tuple[str, bool]],
        tach: str,
        expected_substrings: list[tuple[str, ...]],
    ) -> None:
        for name, isolated in products:
            _mkproduct(tmp_path, name, isolated=isolated)
        issues = validate_facade_alternation(tach, tmp_path)
        if not expected_substrings:
            assert issues == []
            return
        for substrings in expected_substrings:
            assert any(all(s in issue for s in substrings) for issue in issues), (
                f"no issue matched all of {substrings!r}; got {issues!r}"
            )


class TestNamesFromPattern:
    @pytest.mark.parametrize(
        "pattern, expected",
        [
            ("products.experiments", {"experiments"}),
            ("products\\.experiments", {"experiments"}),
            ("products\\\\.experiments", {"experiments"}),
            ("products\\.(a|b|c)", {"a", "b", "c"}),
            ("products\\\\.(a|b|c)", {"a", "b", "c"}),
            ("products\\.(experiments|mcp_store|tracing)", {"experiments", "mcp_store", "tracing"}),
            ("posthog.api", set()),
            ("products.something.deeper", set()),
            ("", set()),
        ],
    )
    def test_extraction(self, pattern: str, expected: set[str]) -> None:
        assert _names_from_pattern(pattern) == expected


# ---------------------------------------------------------------------------
# validate_interface_blocks — per-block structural checks
# ---------------------------------------------------------------------------


def _iface(expose: list[str], frm: str = "products.x") -> str:
    expose_str = ", ".join(f'"{e}"' for e in expose)
    return f'[[interfaces]]\nexpose = [{expose_str}]\nfrom = ["{frm}"]\n'


class TestValidateInterfaceBlocks:
    @pytest.mark.parametrize(
        "expose, expected_issue",
        [
            # Pure facade — clean.
            (["backend\\\\.facade.*", "backend\\\\.presentation\\\\.views.*"], None),
            # Pure legacy — clean.
            (["backend\\\\.models.*", "backend\\\\.logic.*"], None),
            # Mixed facade + internal — error.
            (
                ["backend\\\\.facade.*", "backend\\\\.models.*"],
                "mixes facade/presentation",
            ),
            # Mixed presentation + internal — error.
            (
                ["backend\\\\.presentation\\\\.views.*", "backend\\\\.logic.*"],
                "mixes facade/presentation",
            ),
            # Overly broad: backend.* (raw).
            (["backend.*"], "overly broad"),
            # Overly broad: backend\\..*  (tach regex form).
            (["backend\\\\..*"], "overly broad"),
            # Overly broad: backend.** (globstar).
            (["backend\\\\.**"], "overly broad"),
            # Specific submodule — not broad.
            (["backend\\\\.models.*"], None),
        ],
        ids=[
            "pure_facade",
            "pure_legacy",
            "mixed_facade_internal",
            "mixed_presentation_internal",
            "broad_raw",
            "broad_tach_regex",
            "broad_globstar",
            "specific_submodule",
        ],
    )
    def test_blocks(self, expose: list[str], expected_issue: str | None) -> None:
        tach = _iface(expose)
        issues = validate_interface_blocks(tach)
        if expected_issue is None:
            assert issues == [], f"unexpected issues: {issues}"
        else:
            assert any(expected_issue in i for i in issues), (
                f"expected substring {expected_issue!r} in issues; got {issues!r}"
            )


# ---------------------------------------------------------------------------
# validate_tach_references — referential integrity
# ---------------------------------------------------------------------------


class TestValidateTachReferences:
    @pytest.mark.parametrize(
        "tach, expected_substrings",
        [
            # Clean: interface references existing module.
            (
                '[[modules]]\npath = "products.alpha"\ndepends_on = []\n\n'
                '[[interfaces]]\nexpose = ["backend\\\\.models.*"]\nfrom = ["products.alpha"]\n',
                [],
            ),
            # Dangling interface: references nonexistent module.
            (
                '[[modules]]\npath = "products.alpha"\ndepends_on = []\n\n'
                '[[interfaces]]\nexpose = ["backend\\\\.models.*"]\nfrom = ["products.ghost"]\n',
                [("products.ghost", "dangling interface")],
            ),
            # Dangling depends_on.
            (
                '[[modules]]\npath = "products.alpha"\ndepends_on = ["products.ghost"]\n',
                [("products.ghost", "dangling dependency")],
            ),
            # Clean depends_on.
            (
                '[[modules]]\npath = "products.alpha"\ndepends_on = []\n\n'
                '[[modules]]\npath = "products.beta"\ndepends_on = ["products.alpha"]\n',
                [],
            ),
            # Both dangling.
            (
                '[[modules]]\npath = "products.a"\ndepends_on = ["products.missing_dep"]\n\n'
                '[[interfaces]]\nexpose = ["backend\\\\.x.*"]\nfrom = ["products.missing_iface"]\n',
                [("missing_dep", "dangling dependency"), ("missing_iface", "dangling interface")],
            ),
        ],
        ids=[
            "clean_interface",
            "dangling_interface",
            "dangling_depends_on",
            "clean_depends_on",
            "both_dangling",
        ],
    )
    def test_references(self, tach: str, expected_substrings: list[tuple[str, str]]) -> None:
        issues = validate_tach_references(tach)
        if not expected_substrings:
            assert issues == []
            return
        for substrings in expected_substrings:
            assert any(all(s in issue for s in substrings) for issue in issues), (
                f"no issue matched all of {substrings!r}; got {issues!r}"
            )


# ---------------------------------------------------------------------------
# validate_facade_alternation — alphabetical sort check
# ---------------------------------------------------------------------------


class TestAlternationSorting:
    def test_sorted_passes(self, tmp_path: Path) -> None:
        _mkproduct(tmp_path, "alpha", isolated=True)
        _mkproduct(tmp_path, "beta", isolated=True)
        tach = _iface(
            ["backend\\\\.facade.*", "backend\\\\.presentation\\\\.views.*"],
            "products\\\\.(alpha|beta)",
        )
        assert validate_facade_alternation(tach, tmp_path) == []

    def test_unsorted_fails(self, tmp_path: Path) -> None:
        _mkproduct(tmp_path, "alpha", isolated=True)
        _mkproduct(tmp_path, "beta", isolated=True)
        tach = _iface(
            ["backend\\\\.facade.*", "backend\\\\.presentation\\\\.views.*"],
            "products\\\\.(beta|alpha)",
        )
        issues = validate_facade_alternation(tach, tmp_path)
        assert any("not sorted" in i for i in issues)
