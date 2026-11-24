"""Check framework and all product lint checks.

Lint checks are pass/fail structural correctness checks. They answer "is anything
broken?" — missing files, broken scripts, misplaced code. hoglint holds the
boundaries between products (hoglint.toml).

Progress/maturity scoring lives in maturity.py instead.
"""

from __future__ import annotations

import re
import ast
import json
import shlex
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .ast_helpers import ast_parse_safe


def has_contracts_module(backend_dir: Path) -> bool:
    """A contracts module turns on the strict lint. The file alone is no evidence of isolation,
    because an empty contracts.py satisfies it."""
    return (backend_dir / "facade" / "contracts.py").exists() or (backend_dir / "facade" / "contracts").exists()


# ---------------------------------------------------------------------------
# Check framework
# ---------------------------------------------------------------------------


@dataclass
class CheckContext:
    name: str
    product_dir: Path
    backend_dir: Path
    has_facade_contracts: bool
    structure: dict


@dataclass
class CheckResult:
    lines: list[str] = field(default_factory=list)  # lines printed to stdout
    issues: list[str] = field(default_factory=list)  # blocking issues returned to caller
    warnings: list[str] = field(default_factory=list)  # non-blocking warnings
    file: str | None = None  # file path for GitHub annotations
    skip: bool = False  # silently skip this check


class ProductCheck(ABC):
    label: str
    for_strict: bool = True
    for_lenient: bool = True

    def should_run(self, ctx: CheckContext) -> bool:
        if ctx.has_facade_contracts and not self.for_strict:
            return False
        if not ctx.has_facade_contracts and not self.for_lenient:
            return False
        return True

    @abstractmethod
    def run(self, ctx: CheckContext) -> CheckResult: ...


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


class RequiredRootFilesCheck(ProductCheck):
    label = "required root files"

    def run(self, ctx: CheckContext) -> CheckResult:
        required_key = "required" if ctx.has_facade_contracts else "required_lenient"
        missing = [
            filename
            for filename, config in ctx.structure.get("root_files", {}).items()
            if config.get(required_key, False) and not (ctx.product_dir / filename).exists()
        ]
        if missing:
            return CheckResult(
                lines=[f"✗ missing: {', '.join(missing)}"],
                issues=[f"Missing required root file: {f}" for f in missing],
            )
        return CheckResult(lines=["✓ ok"])


class BackendPackageMarkerCheck(ProductCheck):
    """backend/ and its facade/ and presentation/ trees need an __init__.py in each directory.

    `products` is a regular package. mypy names a file's module by the __init__.py files above it,
    so a directory without the marker cuts the name short, and the modules below it read under a
    wrong name. facade/ and presentation/ are the trees other code imports by name.
    """

    label = "backend package marker"

    # Test directories and generated trees (warehouse_sources' per-source connectors) are namespace
    # dirs on purpose and stay that way.
    CONTRACT_TREES = ("facade", "presentation")

    def should_run(self, ctx: CheckContext) -> bool:
        return ctx.backend_dir.is_dir()

    def _missing_markers(self, ctx: CheckContext) -> list[str]:
        missing = []
        if not (ctx.backend_dir / "__init__.py").exists():
            missing.append("backend/")
        for tree in self.CONTRACT_TREES:
            root = ctx.backend_dir / tree
            if not root.is_dir():
                continue
            for directory in sorted(d for d in root.rglob("*") if d.is_dir()):
                if directory.name == "__pycache__" or not any(directory.glob("*.py")):
                    continue
                if not (directory / "__init__.py").exists():
                    missing.append(f"backend/{directory.relative_to(ctx.backend_dir)}/")
            if not (root / "__init__.py").exists():
                missing.append(f"backend/{tree}/")
        return sorted(set(missing))

    def run(self, ctx: CheckContext) -> CheckResult:
        missing = self._missing_markers(ctx)
        if not missing:
            return CheckResult(lines=["✓ ok"])
        return CheckResult(
            lines=[f"✗ missing __init__.py: {', '.join(missing)}"],
            issues=[
                f"missing __init__.py in {', '.join(missing)} — mypy names a module by the __init__.py "
                "files above it, so the modules below read under a short, wrong name. Add the marker "
                "(empty, like every other product's)"
            ],
        )


def _has_test_files(backend_dir: Path) -> bool:
    """Check if backend/ contains any pytest-discoverable test files."""
    return any(backend_dir.rglob("test_*.py")) or any(backend_dir.rglob("*_test.py"))


def _is_noop_script(script: str) -> bool:
    """Check if a script is a no-op (echo, true, exit 0, etc.)."""
    stripped = script.strip()
    return stripped.startswith("echo ") or stripped in ("true", "exit 0", ":")


def _parse_pytest_paths(script: str) -> list[str]:
    """Extract test path arguments from a pytest command.

    Given something like:
        pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short
    Returns:
        ["backend/tests"]
    """
    try:
        parts = shlex.split(script)
    except ValueError:
        parts = script.split()
    if not parts or parts[0] != "pytest":
        return []

    paths: list[str] = []
    skip_next = False
    for part in parts[1:]:
        if skip_next:
            skip_next = False
            continue
        # flags that consume the next token
        if part in ("-c", "--rootdir", "-k", "-m", "-p", "--override-ini", "-o"):
            skip_next = True
            continue
        # skip flags
        if part.startswith("-"):
            continue
        paths.append(part)
    return paths


class PackageJsonScriptsCheck(ProductCheck):
    label = "package.json scripts"

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        package_json = ctx.product_dir / "package.json"
        try:
            scripts = json.loads(package_json.read_text()).get("scripts", {}) if package_json.exists() else {}
        except json.JSONDecodeError:
            return CheckResult(
                lines=["✗ package.json is not valid JSON"],
                issues=["package.json is not valid JSON"],
            )

        result = CheckResult()

        if "backend:test" not in scripts:
            result.lines.append("✗ missing 'backend:test'")
            result.issues.append(
                "Product has backend/ but package.json is missing 'backend:test' script — "
                "turbo cannot discover this product"
            )

        # --- content checks on backend:test ---
        test_script = scripts.get("backend:test", "")
        if test_script:
            # strip trailing || true / || exit 0 before further checks
            base_script = test_script.split("||")[0].strip()

            # check: || true / || exit 0 swallows failures
            if "||" in test_script:
                tail = test_script.split("||", 1)[1].strip()
                if tail in ("true", "exit 0"):
                    result.lines.append(f"✗ 'backend:test' uses '|| {tail}'")
                    result.issues.append(f"'backend:test' script uses '|| {tail}' which swallows test failures in CI")

            # check: no-op script but test files exist
            if _is_noop_script(base_script) and _has_test_files(ctx.backend_dir):
                result.lines.append("✗ 'backend:test' is a no-op but test files exist")
                result.issues.append(
                    "'backend:test' is a no-op (e.g. echo) but backend/ contains test files "
                    "that will never run — update the script to use pytest"
                )

            # check: pytest paths exist on disk
            if base_script.startswith("pytest"):
                test_paths = _parse_pytest_paths(base_script)
                for tp in test_paths:
                    resolved = ctx.product_dir / tp
                    if not resolved.exists():
                        result.lines.append(f"✗ test path '{tp}' does not exist")
                        result.issues.append(
                            f"'backend:test' references path '{tp}' which does not exist — "
                            "pytest will fail or silently collect zero tests"
                        )

        if not result.issues:
            result.lines.append("✓ ok")
        result.file = f"products/{ctx.name}/package.json"
        return result


class MisplacedFilesCheck(ProductCheck):
    label = "misplaced backend files"
    for_lenient = False

    # Only the root-level files in `backend_known_files` are checked here. Directory
    # names are deliberately not: which internal packages a product has (`logic/`,
    # `services/`, `reviewer/`) is its own business, and the thing that must not
    # drift — presentation code outside presentation/ — is enforced by shape in
    # hoglint's `presentation-uses-facade` rule: routes.py and presentation/ reach product
    # code only through the facade, so a view anywhere else cannot be routed.

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        misplaced = []
        for filename, correct_path in ctx.structure.get("backend_known_files", {}).items():
            wrong = ctx.backend_dir / filename
            correct = ctx.backend_dir / correct_path
            if wrong.exists() and wrong.is_file():
                if correct.exists():
                    misplaced.append(f"'{filename}' at backend/ root conflicts with correct location '{correct_path}'")
                else:
                    misplaced.append(f"backend/{filename} should be at backend/{correct_path}")

        if misplaced:
            return CheckResult(
                lines=[f"✗ {len(misplaced)} misplaced file(s)"] + [f"  → {m}" for m in misplaced],
                issues=misplaced,
            )
        return CheckResult(lines=["✓ ok"])


class FileFolderConflictsCheck(ProductCheck):
    label = "file/folder conflicts"

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        # Collect "<name>" stems that may be expressed as either a file or a
        # package, from two structure shapes:
        #   - "<name>.py" with `can_be_folder: true`        (e.g. models.py)
        #   - "<name>/" as a top-level backend_files entry  (e.g. logic/, facade/)
        # Subdirectories qualify whether or not they declare an `__init__.py`
        # in the structure — namespace packages are fine, and this also catches
        # a stray `tasks.py` next to `tasks/`, which is always a mistake.
        stems: set[str] = set()
        for name, config in ctx.structure.get("backend_files", {}).items():
            if name.endswith("/"):
                stems.add(name.rstrip("/"))
            elif name.endswith(".py") and isinstance(config, dict) and config.get("can_be_folder", False):
                stems.add(name[: -len(".py")])

        # Conflict if both `<stem>.py` and `<stem>/` directory exist on disk.
        # Check the directory itself (not `__init__.py`) so a half-migrated state
        # without `__init__.py` is still flagged.
        conflicts = []
        for stem in sorted(stems):
            file_form = ctx.backend_dir / f"{stem}.py"
            dir_form = ctx.backend_dir / stem
            if file_form.is_file() and dir_form.is_dir():
                conflicts.append(f"Both 'backend/{stem}.py' and 'backend/{stem}/' exist — pick one")

        if conflicts:
            return CheckResult(
                lines=[f"✗ {len(conflicts)} conflict(s)"] + [f"  → {c}" for c in conflicts],
                issues=conflicts,
            )
        return CheckResult(lines=["✓ ok"])


class ProductYamlCheck(ProductCheck):
    """Validates product.yaml exists, parses, and has correct field types."""

    label = "product.yaml"

    def run(self, ctx: CheckContext) -> CheckResult:
        from .product_yaml import parse_product_yaml

        yaml_path = ctx.product_dir / "product.yaml"

        if not yaml_path.exists():
            return CheckResult(
                lines=["✗ missing"],
                issues=["Missing product.yaml — every product needs name and owners"],
                file=f"products/{ctx.name}",
            )

        result = CheckResult(file=f"products/{ctx.name}/product.yaml")

        data, parse_err = parse_product_yaml(yaml_path)
        if parse_err:
            result.issues.append(f"product.yaml {parse_err}")
            result.lines = [f"✗ {result.issues[0]}"]
            return result

        name = data.get("name")
        if not name or not isinstance(name, str):
            result.issues.append("product.yaml missing 'name' field (must be a non-empty string)")

        owners = data.get("owners")
        if not owners:
            result.issues.append("product.yaml missing 'owners' field — who owns this product?")
        elif not isinstance(owners, list) or not all(isinstance(o, str) for o in owners):
            result.issues.append("product.yaml 'owners' must be a list of strings")

        # The owners resolver ignores a value that is not a boolean, so a typo here would silently leave the paths
        # not sensitive.
        if "sensitive" in data and not isinstance(data["sensitive"], bool):
            result.issues.append("product.yaml 'sensitive' must be true or false")

        if result.issues:
            result.lines = [f"✗ {len(result.issues)} issue(s)"] + [f"  → {i}" for i in result.issues]
        else:
            result.lines = ["✓ ok"]
        return result


class ProductYamlOwnersCheck(ProductCheck):
    """Validates product.yaml owner slugs against GitHub team slugs in the PostHog org.

    Not part of the default CHECKS list — pays a GitHub API call per run, so it's
    only invoked via the dedicated ``product:lint:owners`` subcommand. CI gates
    that subcommand on a ``products/*/product.yaml`` paths filter, so the API
    call only fires when an ownership change is actually proposed.

    Validates "team exists in the org", not "team has access to this repo" — the
    repo-collaborator endpoint needs a permission the assign-reviewers GH App
    lacks. The "exists but lacks repo access" gap is covered by the script's
    422 fallback (drops bad teams, keeps valid ones).
    """

    label = "product.yaml owners"

    def run(self, ctx: CheckContext) -> CheckResult:
        from .gh import get_team_slugs
        from .product_yaml import parse_product_yaml

        yaml_path = ctx.product_dir / "product.yaml"
        if not yaml_path.exists():
            return CheckResult(skip=True)

        data, parse_err = parse_product_yaml(yaml_path)
        if parse_err:
            return CheckResult(skip=True)

        owners = data.get("owners")
        if not owners or not isinstance(owners, list):
            return CheckResult(skip=True)

        gh_teams, fetch_err = get_team_slugs()
        if gh_teams is None:
            return CheckResult(
                lines=[f"✗ {fetch_err}"],
                issues=[fetch_err],
                file=f"products/{ctx.name}/product.yaml",
            )

        result = CheckResult(file=f"products/{ctx.name}/product.yaml")

        for owner in owners:
            if not isinstance(owner, str):
                continue
            # `@username` entries are individual reviewers, not teams — validating
            # them needs a different endpoint, and the assign-reviewers script
            # already routes them separately. Skip here.
            if owner.startswith("@"):
                continue
            if owner == "team-CHANGEME":
                result.issues.append(
                    "owner is still the 'team-CHANGEME' scaffold placeholder — pick a real owning team"
                )
                continue
            if owner not in gh_teams:
                result.issues.append(
                    f"owner '{owner}' is not a GitHub team in the PostHog org. "
                    f"See https://github.com/orgs/PostHog/teams"
                )

        if result.issues:
            result.lines = [f"✗ {len(result.issues)} issue(s)"] + [f"  → {i}" for i in result.issues]
        else:
            result.lines = ["✓ ok"]
        return result


class OrphanedTestFilesCheck(ProductCheck):
    """Flag pytest test files that no CI runner will pick up.

    Walks the product directory for `test_*.py` / `*_test.py` and checks each
    is reachable from either:
      - the pytest paths listed in `backend:test`, or
      - a known external runner via `_EXTERNAL_RUNNER_PREFIXES` (e.g. `dags/`
        directories are picked up by ci-dagster.yml, regardless of the
        product's package.json).

    Without this check, moving a test file to (say) `products/foo/scripts/test/`
    or forgetting to add it to `backend:test` silently strands the tests —
    they collect cleanly when run by hand but never run in CI.
    """

    label = "test file coverage"

    # Directories whose test files are run by workflows other than the product
    # matrix. Keep in sync with the workflows under `.github/workflows/` that
    # invoke pytest against product paths.
    _EXTERNAL_RUNNER_PREFIXES = (
        "dags/",  # ci-dagster.yml: pytest posthog/dags products/**/dags
    )
    # Exempt paths tested outside `backend:test`, including the Temporal tests in
    # .depot/workflows/ci-backend.yml.
    _PRODUCT_SPECIFIC_EXEMPTIONS = {
        # .depot/workflows/ci-backend.yml "Run Temporal tests" step pytest paths:
        "batch_exports": ("backend/tests/temporal/",),
        "tasks": ("backend/temporal/",),
        # backend/temporal/ is the Temporal segment above. sources/ holds the vendor plugins, which
        # the "Warehouse sources checks and tests" job in ci-python.yml runs.
        "warehouse_sources": ("backend/temporal/", "sources/"),
        "signals": ("backend/emission/",),
        # Covered by the "Run pr-approval-agent (stamphog) tests" step in ci-python.yml. The review
        # engine is a flat script bundle with bare sibling imports, so it runs as its own pytest
        # invocation rather than inside the product's Django suite.
        "stamphog": ("packages/pr-approval-agent/",),
    }

    def run(self, ctx: CheckContext) -> CheckResult:
        # Find every test file under the product.
        test_files = sorted(
            p.relative_to(ctx.product_dir).as_posix()
            for pattern in ("test_*.py", "*_test.py")
            for p in ctx.product_dir.rglob(pattern)
            if "__pycache__" not in p.parts
        )
        if not test_files:
            return CheckResult(skip=True)

        # Extract the pytest paths from backend:test, if present.
        package_json = ctx.product_dir / "package.json"
        scripts = {}
        if package_json.exists():
            try:
                scripts = json.loads(package_json.read_text()).get("scripts", {})
            except json.JSONDecodeError:
                pass  # PackageJsonScriptsCheck reports the invalid JSON
        test_script = scripts.get("backend:test", "")
        base_script = test_script.split("||")[0].strip() if test_script else ""
        if base_script.startswith("pytest"):
            pytest_paths = _parse_pytest_paths(base_script)
        else:
            pytest_paths = []

        def _covered_by(rel: str, path: str) -> bool:
            # pytest path can be a file ("backend/test_max_tools.py") or a
            # directory ("backend/" or "scripts/test"). Treat as a prefix
            # match against the trailing slash to avoid "backend/" eating
            # "backend_tools/foo.py".
            if rel == path:
                return True
            return rel.startswith(path.rstrip("/") + "/")

        result = CheckResult()
        per_product = self._PRODUCT_SPECIFIC_EXEMPTIONS.get(ctx.name, ())
        orphans = []
        for rel in test_files:
            if any(_covered_by(rel, p) for p in self._EXTERNAL_RUNNER_PREFIXES):
                continue
            if any(_covered_by(rel, p) for p in per_product):
                continue
            if any(_covered_by(rel, p) for p in pytest_paths):
                continue
            orphans.append(rel)

        if orphans:
            result.lines.append(
                f"✗ {len(orphans)} test file(s) not reachable from backend:test or any known external runner"
            )
            for o in orphans:
                result.lines.append(f"  → {o}")
            result.issues.extend(
                f"Test file {o} is not covered by backend:test pytest paths or a known "
                "external runner (e.g. ci-dagster.yml for dags/). It will never run in CI"
                for o in orphans
            )
            result.file = f"products/{ctx.name}/package.json"
        else:
            result.lines.append("✓ ok")
        return result


# A string shaped like a Django system check ID: dotted words, then a level letter and three digits.
_SYSTEM_CHECK_ID_RE = re.compile(r"^[A-Za-z_][\w.]*\.[A-Z]\d{3}$")
# Each module that registers system checks, mapped to its register function.
_REGISTER_FUNCTIONS = {"django.core.checks": "register", "posthog.checks": "register_check"}


def _register_bindings(tree: ast.Module) -> tuple[set[str], dict[str, str]]:
    """Local names bound to a register function, and local module names mapped to their register function."""
    register_names: set[str] = set()
    module_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                bound = alias.asname or alias.name
                if _REGISTER_FUNCTIONS.get(node.module) == alias.name:
                    register_names.add(bound)
                elif (module := f"{node.module}.{alias.name}") in _REGISTER_FUNCTIONS:
                    module_names[bound] = _REGISTER_FUNCTIONS[module]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _REGISTER_FUNCTIONS:
                    module_names[alias.asname or alias.name] = _REGISTER_FUNCTIONS[alias.name]
    return register_names, module_names


def _registers_system_check(tree: ast.Module) -> bool:
    """Whether the module registers a Django system check, through Django or posthog.checks."""
    register_names, module_names = _register_bindings(tree)

    def _is_register(func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in register_names
        return isinstance(func, ast.Attribute) and module_names.get(ast.unparse(func.value)) == func.attr

    return any(
        (isinstance(node, ast.Call) and _is_register(node.func))
        or (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and any(_is_register(decorator) for decorator in node.decorator_list)
        )
        for node in ast.walk(tree)
    )


def _system_check_ids(tree: ast.Module) -> list[str]:
    return sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _SYSTEM_CHECK_ID_RE.match(node.value)
        }
    )


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_imports(statements: list[ast.stmt]) -> Iterator[ast.Import | ast.ImportFrom]:
    """Imports that run when the statements run: not in a nested def or class, or a type-checking-only branch."""
    for stmt in statements:
        if isinstance(stmt, ast.Import | ast.ImportFrom):
            yield stmt
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        elif isinstance(stmt, ast.If) and _is_type_checking(stmt.test):
            yield from _runtime_imports(stmt.orelse)
        elif (
            isinstance(stmt, ast.If)
            and isinstance(stmt.test, ast.UnaryOp)
            and isinstance(stmt.test.op, ast.Not)
            and _is_type_checking(stmt.test.operand)
        ):
            yield from _runtime_imports(stmt.body)
        else:
            for nested in ("body", "orelse", "finalbody"):
                yield from _runtime_imports(getattr(stmt, nested, []))
            for handler in getattr(stmt, "handlers", []):
                yield from _runtime_imports(handler.body)


def _imports_checks_module(node: ast.Import | ast.ImportFrom, backend: str) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name == f"{backend}.checks" for alias in node.names)
    names = {alias.name for alias in node.names}
    if node.level == 0:
        return node.module == f"{backend}.checks" or (node.module == backend and "checks" in names)
    return node.level == 1 and (node.module == "checks" or (node.module is None and "checks" in names))


def _ready_imports_checks(apps_path: Path, product: str) -> bool:
    """Whether an AppConfig.ready() in apps.py imports the product's backend/checks.py when it runs."""
    tree = ast_parse_safe(apps_path) if apps_path.exists() else None
    if tree is None:
        return False
    backend = f"products.{product}.backend"
    return any(
        _imports_checks_module(node, backend)
        for class_node in tree.body
        if isinstance(class_node, ast.ClassDef)
        for ready in class_node.body
        if isinstance(ready, ast.FunctionDef) and ready.name == "ready"
        for node in _runtime_imports(ready.body)
    )


class SystemChecksCheck(ProductCheck):
    """A product's Django system checks live in backend/checks.py, which apps.py ready() imports.

    Django only runs a check whose module has been imported, so a check anywhere else, or a
    checks.py that ready() never imports, is silently never run. IDs follow the scheme in
    posthog/checks.py, with the product name as the area.
    """

    label = "system checks"

    @staticmethod
    def _misplaced_registrations(backend_dir: Path) -> list[str]:
        problems: list[str] = []
        for path in sorted(backend_dir.rglob("*.py")):
            rel = path.relative_to(backend_dir)
            if rel == Path("checks.py") or {"__pycache__", "test", "tests"}.intersection(rel.parts):
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                continue
            tree = ast_parse_safe(path)
            if tree is not None and _registers_system_check(tree):
                problems.append(
                    f"backend/{rel.as_posix()} registers a Django system check: move it to backend/checks.py"
                )
        return problems

    @staticmethod
    def _checks_module_problems(ctx: CheckContext) -> list[str]:
        tree = ast_parse_safe(ctx.backend_dir / "checks.py")
        prefix = f"posthog.{ctx.name}."
        problems = [
            f"backend/checks.py uses check ID {check_id!r}, which must start with {prefix!r}"
            for check_id in (_system_check_ids(tree) if tree is not None else [])
            if not check_id.startswith(prefix)
        ]
        if not _ready_imports_checks(ctx.backend_dir / "apps.py", ctx.name):
            problems.append(
                "backend/checks.py is never imported by apps.py ready(), so Django never registers its checks"
            )
        return problems

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        problems = self._misplaced_registrations(ctx.backend_dir)
        if (ctx.backend_dir / "checks.py").exists():
            problems.extend(self._checks_module_problems(ctx))

        if problems:
            return CheckResult(
                lines=[f"✗ {len(problems)} problem(s)"] + [f"  → {p}" for p in problems],
                issues=problems,
            )
        return CheckResult(lines=["✓ ok"])


CHECKS: list[ProductCheck] = [
    ProductYamlCheck(),
    RequiredRootFilesCheck(),
    BackendPackageMarkerCheck(),
    PackageJsonScriptsCheck(),
    MisplacedFilesCheck(),
    FileFolderConflictsCheck(),
    OrphanedTestFilesCheck(),
    SystemChecksCheck(),
]
