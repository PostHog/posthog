"""Tests for product lint checks — focused on PackageJsonScriptsCheck."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hogli_commands.product import gh as gh_module
from hogli_commands.product.checks import (
    BackendPackageMarkerCheck,
    CheckContext,
    FileFolderConflictsCheck,
    OrphanedTestFilesCheck,
    PackageJsonScriptsCheck,
    ProductYamlCheck,
    ProductYamlOwnersCheck,
    SystemChecksCheck,
    _has_test_files,
    _is_noop_script,
    _parse_pytest_paths,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(
    tmp_path: Path,
    *,
    scripts: dict[str, str] | None = None,
    has_backend: bool = True,
    strict: bool = False,
    test_files: list[str] | None = None,
    extra_dirs: list[str] | None = None,
) -> CheckContext:
    """Build a minimal product directory and return a CheckContext for it."""
    product_dir = tmp_path / "my_product"
    product_dir.mkdir()
    backend_dir = product_dir / "backend"

    if has_backend:
        backend_dir.mkdir()

    if strict:
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
        has_facade_contracts=strict,
        structure={},
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

    def test_invalid_json_returns_issue(self, tmp_path: Path) -> None:
        ctx = _make_product(tmp_path, has_backend=True)
        (ctx.product_dir / "package.json").write_text("{invalid json")
        result = check.run(ctx)
        assert any("not valid JSON" in i for i in result.issues)


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
            strict=True,
            test_files=["tests/test_api.py"],
        )
        result = check.run(ctx)
        assert not result.issues
        assert any("✓ ok" in line for line in result.lines)

    def test_fully_valid_legacy_product(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            strict=False,
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
            strict=False,
        )
        result = check.run(ctx)
        # Should report: || true, nonexistent path
        assert len(result.issues) >= 2


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
        has_facade_contracts=False,
        structure={},
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

    @pytest.mark.parametrize("value,valid", [("true", True), ("false", True), ("'true'", False), ("yes please", False)])
    def test_sensitive_must_be_boolean(self, tmp_path: Path, value: str, valid: bool) -> None:
        ctx = _make_yaml_ctx(tmp_path, f"name: My product\nowners:\n  - team-foo\nsensitive: {value}\n")
        result = yaml_check.run(ctx)
        assert (not result.issues) is valid, result.issues


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
        monkeypatch.setattr(gh_module, "get_team_slugs", lambda: ({"team-real"}, ""))
        result = owners_check.run(ctx)
        assert any("team-nonexistent" in i for i in result.issues)

    def test_valid_slug_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - team-real\n")
        monkeypatch.setattr(gh_module, "get_team_slugs", lambda: ({"team-real"}, ""))
        result = owners_check.run(ctx)
        assert not result.issues

    def test_gh_unavailable_is_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _make_yaml_ctx(tmp_path, "name: My product\nowners:\n  - team-foo\n")
        monkeypatch.setattr(gh_module, "get_team_slugs", lambda: (None, "gh CLI not found"))
        result = owners_check.run(ctx)
        assert result.issues
        assert any("gh CLI" in i for i in result.issues)


# ---------------------------------------------------------------------------
# FileFolderConflictsCheck — file vs package twin detection
# ---------------------------------------------------------------------------

# Structure mirrors product_structure.yaml: subdirs (logic/, tasks/, facade/)
# are packages regardless of whether they declare an __init__.py in the
# structure; models can be either a file or folder via can_be_folder.
_CONFLICT_STRUCTURE = {
    "backend_files": {
        "models.py": {"can_be_folder": True},
        "logic/": {"__init__.py": {}},
        "tasks/": {"tasks.py": {}},  # no __init__.py declared — namespace package
        "facade/": {"api.py": {}, "contracts.py": {}},
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
        has_facade_contracts=False,
        structure=_CONFLICT_STRUCTURE,
    )


class TestFileFolderConflictsCheck:
    def test_skip_when_no_backend(self, tmp_path: Path) -> None:
        product_dir = tmp_path / "p"
        product_dir.mkdir()
        ctx = CheckContext(
            name="p",
            product_dir=product_dir,
            backend_dir=product_dir / "backend",
            has_facade_contracts=False,
            structure=_CONFLICT_STRUCTURE,
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
            # Namespace-package subdir (no __init__.py declared in structure) — stem still detected
            (["facade/api.py"], []),
            (["facade.py", "facade/api.py"], ["facade.py"]),
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
# OrphanedTestFilesCheck — ensures every product test file is reachable by
# either backend:test or a known external runner.
# ---------------------------------------------------------------------------


class TestOrphanedTestFilesCheck:
    """Verifies the lint catches test files left behind by misconfigured scripts."""

    _orphan_check = OrphanedTestFilesCheck()

    def _ctx(self, tmp_path: Path, *, scripts: dict[str, str] | None = None, name: str = "my_product") -> CheckContext:
        product_dir = tmp_path / name
        product_dir.mkdir()
        backend_dir = product_dir / "backend"
        backend_dir.mkdir()
        if scripts is not None:
            (product_dir / "package.json").write_text(json.dumps({"scripts": scripts}))
        return CheckContext(
            name=name,
            product_dir=product_dir,
            backend_dir=backend_dir,
            has_facade_contracts=False,
            structure={},
        )

    def test_skip_when_no_test_files(self, tmp_path: Path) -> None:
        ctx = self._ctx(tmp_path)
        result = self._orphan_check.run(ctx)
        assert result.skip is True

    def test_orphan_flagged_when_backend_test_missing(self, tmp_path: Path) -> None:
        ctx = self._ctx(tmp_path)
        (ctx.backend_dir / "api" / "test").mkdir(parents=True)
        (ctx.backend_dir / "api" / "test" / "test_thing.py").write_text("")
        result = self._orphan_check.run(ctx)
        assert any("backend/api/test/test_thing.py" in line for line in result.lines)
        assert result.issues

    def test_no_orphans_when_backend_test_covers(self, tmp_path: Path) -> None:
        ctx = self._ctx(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
        )
        (ctx.backend_dir / "api" / "test").mkdir(parents=True)
        (ctx.backend_dir / "api" / "test" / "test_thing.py").write_text("")
        result = self._orphan_check.run(ctx)
        assert not result.issues

    def test_specific_file_path_in_pytest_does_not_false_flag(self, tmp_path: Path) -> None:
        ctx = self._ctx(
            tmp_path,
            scripts={"backend:test": "pytest backend/test_max_tools.py -v"},
        )
        (ctx.backend_dir / "test_max_tools.py").write_text("")
        result = self._orphan_check.run(ctx)
        assert not result.issues

    def test_directory_prefix_does_not_eat_unrelated_paths(self, tmp_path: Path) -> None:
        ctx = self._ctx(
            tmp_path,
            scripts={"backend:test": "pytest backend/api"},
        )
        (ctx.backend_dir / "api").mkdir()
        (ctx.backend_dir / "api" / "test_covered.py").write_text("")
        (ctx.backend_dir / "api_v2").mkdir()
        (ctx.backend_dir / "api_v2" / "test_uncovered.py").write_text("")
        result = self._orphan_check.run(ctx)
        assert any("api_v2/test_uncovered.py" in i for i in result.issues)
        assert not any("api/test_covered.py" in i for i in result.issues)

    def test_dags_tests_exempted_via_external_runner(self, tmp_path: Path) -> None:
        # ci-dagster.yml runs `pytest products/**/dags`. The check should not
        # flag test files under `dags/` even when backend:test doesn't cover them.
        ctx = self._ctx(tmp_path, scripts={"backend:test": "pytest backend/"})
        (ctx.product_dir / "dags" / "tests").mkdir(parents=True)
        (ctx.product_dir / "dags" / "tests" / "test_thing.py").write_text("")
        result = self._orphan_check.run(ctx)
        assert not result.issues

    def test_per_product_exemption_applied(self, tmp_path: Path) -> None:
        # products/tasks/backend/temporal/ is covered by ci-backend.yml Temporal
        # segment, not the product matrix.
        ctx = self._ctx(
            tmp_path,
            scripts={"backend:test": "pytest backend/tests backend/services"},
            name="tasks",
        )
        (ctx.backend_dir / "temporal" / "tests").mkdir(parents=True)
        (ctx.backend_dir / "temporal" / "tests" / "test_workflow.py").write_text("")
        result = self._orphan_check.run(ctx)
        assert not result.issues

    def test_per_product_exemption_does_not_apply_to_other_products(self, tmp_path: Path) -> None:
        ctx = self._ctx(
            tmp_path,
            scripts={"backend:test": "pytest backend/tests"},
            name="not_tasks",
        )
        (ctx.backend_dir / "temporal" / "tests").mkdir(parents=True)
        (ctx.backend_dir / "temporal" / "tests" / "test_workflow.py").write_text("")
        result = self._orphan_check.run(ctx)
        assert any("backend/temporal/tests/test_workflow.py" in i for i in result.issues)


class TestBackendPackageMarker:
    check = BackendPackageMarkerCheck()

    def _product(self, tmp_path: Path, *, markers: list[str], trees: list[str]) -> CheckContext:
        ctx = _make_product(tmp_path, strict=True)
        for tree in trees:
            (ctx.backend_dir / tree).mkdir(parents=True, exist_ok=True)
            (ctx.backend_dir / tree / "views.py").write_text("x = 1\n")
        for marker in markers:
            (ctx.backend_dir / marker / "__init__.py").write_text("")
        return ctx

    @pytest.mark.parametrize(
        "markers, expected",
        [
            # every level marked -> each module has its full dotted name
            ([".", "facade", "presentation", "presentation/views"], set()),
            # backend/ alone is not enough: mypy stops at the first unmarked level, so
            # every module below reads under a short name
            ([".", "facade", "presentation"], {"backend/presentation/views/"}),
            ([".", "facade"], {"backend/presentation/", "backend/presentation/views/"}),
            # missing at the root hides the entire backend
            (["facade", "presentation", "presentation/views"], {"backend/"}),
        ],
    )
    def test_missing_markers_on_contract_paths(self, tmp_path: Path, markers: list[str], expected: set[str]) -> None:
        ctx = self._product(tmp_path, markers=markers, trees=["presentation", "presentation/views"])
        assert set(self.check._missing_markers(ctx)) == expected

    def test_directories_outside_the_contract_trees_are_left_alone(self, tmp_path: Path) -> None:
        # test dirs and generated trees are namespace packages on purpose — flagging them would
        # mean thousands of pointless files
        ctx = self._product(tmp_path, markers=[".", "facade"], trees=[])
        (ctx.backend_dir / "temporal" / "sources" / "stripe").mkdir(parents=True)
        (ctx.backend_dir / "temporal" / "sources" / "stripe" / "source.py").write_text("x = 1\n")
        (ctx.backend_dir / "tests").mkdir()
        (ctx.backend_dir / "tests" / "test_thing.py").write_text("x = 1\n")
        assert self.check._missing_markers(ctx) == []

    def test_empty_directories_need_no_marker(self, tmp_path: Path) -> None:
        ctx = self._product(tmp_path, markers=[".", "facade"], trees=[])
        (ctx.backend_dir / "facade" / "empty").mkdir()
        assert self.check._missing_markers(ctx) == []


# ---------------------------------------------------------------------------
# SystemChecksCheck — Django system checks live in backend/checks.py
# ---------------------------------------------------------------------------

_READY_IMPORTS_CHECKS = """
from django.apps import AppConfig


class PConfig(AppConfig):
    name = "products.p.backend"

    def ready(self):
        from products.p.backend import checks  # noqa: F401
"""

_READY_WITHOUT_CHECKS = """
from django.apps import AppConfig


class PConfig(AppConfig):
    name = "products.p.backend"
"""

_CHECKS_MODULE = """
from posthog.checks import register_check

P_CHECK = "{check_id}"


@register_check(P_CHECK)
def check_p(app_configs, **kwargs):
    return []
"""

_DJANGO_REGISTER_ELSEWHERE = """
from django.core import checks


@checks.register()
def check_p(app_configs, **kwargs):
    return []
"""


def _system_checks_ctx(tmp_path: Path, files: dict[str, str]) -> CheckContext:
    product_dir = tmp_path / "p"
    backend = product_dir / "backend"
    backend.mkdir(parents=True)
    for rel, content in files.items():
        (backend / rel).parent.mkdir(parents=True, exist_ok=True)
        (backend / rel).write_text(content)
    return CheckContext(
        name="p",
        product_dir=product_dir,
        backend_dir=backend,
        has_facade_contracts=False,
        structure={},
    )


class TestSystemChecksCheck:
    @pytest.mark.parametrize(
        "files, expected",
        [
            ({"apps.py": _READY_WITHOUT_CHECKS}, []),
            (
                {"apps.py": _READY_IMPORTS_CHECKS, "checks.py": _CHECKS_MODULE.format(check_id="posthog.p.E001")},
                [],
            ),
            (
                {
                    "apps.py": _READY_IMPORTS_CHECKS.replace(
                        "from products.p.backend import checks", "from . import checks"
                    ),
                    "checks.py": _CHECKS_MODULE.format(check_id="posthog.p.W001"),
                },
                [],
            ),
            (
                {"apps.py": _READY_WITHOUT_CHECKS, "logic/settings_guard.py": _DJANGO_REGISTER_ELSEWHERE},
                ["backend/logic/settings_guard.py registers a Django system check"],
            ),
            (
                {"apps.py": _READY_IMPORTS_CHECKS, "checks.py": _CHECKS_MODULE.format(check_id="p.E001")},
                ["check ID 'p.E001'"],
            ),
            (
                {"apps.py": _READY_IMPORTS_CHECKS, "checks.py": _CHECKS_MODULE.format(check_id="posthog.other.E001")},
                ["check ID 'posthog.other.E001'"],
            ),
            (
                {"apps.py": _READY_WITHOUT_CHECKS, "checks.py": _CHECKS_MODULE.format(check_id="posthog.p.E001")},
                ["never imported by apps.py ready()"],
            ),
            (
                {
                    "apps.py": _READY_WITHOUT_CHECKS,
                    "logic/guard.py": "import posthog.checks as checks\n\n\n@checks.register_check('posthog.p.W001')\n"
                    "def check_p(app_configs, **kwargs):\n    return []\n",
                },
                ["backend/logic/guard.py registers a Django system check"],
            ),
            (
                {
                    "apps.py": _READY_IMPORTS_CHECKS.replace(
                        "        from products.p.backend import checks",
                        "        from typing import TYPE_CHECKING\n\n        if TYPE_CHECKING:\n"
                        "            from products.p.backend import checks",
                    ),
                    "checks.py": _CHECKS_MODULE.format(check_id="posthog.p.E001"),
                },
                ["never imported by apps.py ready()"],
            ),
            (
                {
                    "apps.py": _READY_IMPORTS_CHECKS.replace(
                        "        from products.p.backend import checks",
                        "        import typing\n\n        if not typing.TYPE_CHECKING:\n"
                        "            from products.p.backend import checks",
                    ),
                    "checks.py": _CHECKS_MODULE.format(check_id="posthog.p.E001"),
                },
                [],
            ),
        ],
    )
    def test_system_check_placement_ids_and_registration(
        self, tmp_path: Path, files: dict[str, str], expected: list[str]
    ) -> None:
        issues = SystemChecksCheck().run(_system_checks_ctx(tmp_path, files)).issues
        assert len(issues) == len(expected), issues
        for fragment, issue in zip(expected, issues):
            assert fragment in issue
