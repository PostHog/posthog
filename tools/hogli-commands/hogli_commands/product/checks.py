"""Check framework and all product lint checks.

Lint checks are pass/fail structural correctness checks. They answer "is anything
broken?" — missing files, broken scripts, misplaced code.

Progress/maturity scoring lives in maturity.py instead.
"""

from __future__ import annotations

import re
import json
import shlex
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .isolation import (
    IsolationStatus,
    compute_isolation_status,
    has_legacy_interface_leaks,
    has_routes_module,
    has_tach_interface,
    is_isolated_product,
    iter_interface_blocks as _iter_interface_blocks,
    names_from_pattern as _names_from_pattern,
    pattern_targets_public_surface as _pattern_targets_public_surface,
    routes_in_turbo_inputs,
)
from .paths import TACH_TOML, get_tach_block

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def check_file_exists(backend_dir: Path, path: str) -> bool:
    """Check if a file or its folder equivalent exists."""
    file_path = backend_dir / path
    if file_path.exists():
        return True
    if path.endswith(".py"):
        folder_path = backend_dir / path.replace(".py", "")
        if folder_path.exists() and folder_path.is_dir():
            return True
    return False


def _iter_module_blocks(tach_content: str) -> Iterator[tuple[str, list[str]]]:
    """Yield (path, depends_on) for every [[modules]] block."""
    for match in re.finditer(r"\[\[modules\]\]\s*\n(.*?)(?=\[\[|\Z)", tach_content, re.DOTALL):
        block = match.group(1)
        path_match = re.search(r'path\s*=\s*"(.*?)"', block)
        if not path_match:
            continue
        path = path_match.group(1)
        deps_match = re.search(r"depends_on\s*=\s*\[(.*?)\]", block, re.DOTALL)
        depends_on = re.findall(r'"(.*?)"', deps_match.group(1)) if deps_match else []
        yield path, depends_on


# ---------------------------------------------------------------------------
# Canonical facade alternation validation (global, not per-product)
# ---------------------------------------------------------------------------


def _targets_facade_or_presentation(pattern: str) -> bool:
    """True if a pattern targets backend.facade or backend.presentation specifically.

    Narrower than `_pattern_targets_public_surface`, which also accepts
    backend.routes. A routes-only block is a registration hook, not a canonical
    facade surface, so it must not be treated as one (it would otherwise demand
    facade/contracts.py isolation scaffolding the product may not have).
    """
    normalized = pattern.replace("\\", "")
    return normalized.startswith("backend.facade") or normalized.startswith("backend.presentation")


def _is_canonical_facade_expose(expose_patterns: list[str]) -> bool:
    """Canonical = a public-surface block that actually exposes facade/presentation.

    Every pattern must be public surface (facade/presentation/routes) and at
    least one must be facade/presentation — so a routes-only registration block
    does not get treated as a canonical facade alternation entry.
    """
    if not expose_patterns:
        return False
    if not all(_pattern_targets_public_surface(p) for p in expose_patterns):
        return False
    return any(_targets_facade_or_presentation(p) for p in expose_patterns)


def validate_facade_alternation(tach_content: str, products_dir: Path) -> list[str]:
    """Validate the canonical facade `[[interfaces]]` block(s).

    Catches stale entries:
      1. Every product named in the canonical alternation must exist as
         products/<name>/.
      2. Every product named in the canonical alternation must have
         backend/facade/contracts.py (be isolated).
      3. Names in alternation regexes must be sorted alphabetically.

    The inverse direction ("every isolated product must be listed") is not
    enforced — having `facade/contracts.py` is just scaffolding and doesn't
    mean the product is ready for canonical exposure.
    """
    issues: list[str] = []

    canonical_names: set[str] = set()
    found_canonical_block = False
    for expose_patterns, from_patterns in _iter_interface_blocks(tach_content):
        if not _is_canonical_facade_expose(expose_patterns):
            continue
        found_canonical_block = True
        for pattern in from_patterns:
            names = _names_from_pattern(pattern)
            if not names:
                issues.append(
                    f"canonical [[interfaces]] block has unparseable from pattern '{pattern}' — "
                    "expected 'products.<name>' or 'products\\.(name1|name2|...)'"
                )
                continue
            canonical_names |= names
            names_list = _ordered_names_from_alternation(pattern)
            if names_list and names_list != sorted(names_list):
                issues.append(
                    f"canonical alternation is not sorted alphabetically — expected '{('|'.join(sorted(names_list)))}'"
                )

    if not found_canonical_block:
        return issues

    for name in sorted(canonical_names):
        product_dir = products_dir / name
        if not product_dir.is_dir():
            issues.append(
                f"canonical facade alternation lists '{name}' but products/{name}/ does not exist — "
                "remove the stale entry from tach.toml"
            )
            continue
        if not is_isolated_product(product_dir / "backend"):
            issues.append(
                f"canonical facade alternation lists '{name}' but products/{name}/backend/facade/contracts.py "
                "is missing — either add contracts.py or remove the entry from tach.toml"
            )

    return issues


def _ordered_names_from_alternation(pattern: str) -> list[str] | None:
    """Return names in their original order if the pattern is an alternation, else None."""
    normalized = pattern.replace("\\", "")
    m = re.match(r"^products\.\(([^)]+)\)$", normalized)
    if m:
        return [n.strip() for n in m.group(1).split("|") if n.strip()]
    return None


def validate_interface_blocks(tach_content: str) -> list[str]:
    """Validate individual [[interfaces]] blocks for structural problems.

    Checks:
      1. No mixed facade + internal expose in a single block.
      2. No overly broad expose patterns (backend.* catches everything).
    """
    issues: list[str] = []

    for expose_patterns, from_patterns in _iter_interface_blocks(tach_content):
        products = set()
        for p in from_patterns:
            products |= _names_from_pattern(p)
        product_label = ", ".join(sorted(products)) or ", ".join(from_patterns)

        has_facade = any(_pattern_targets_public_surface(p) for p in expose_patterns)
        has_internal = any(not _pattern_targets_public_surface(p) for p in expose_patterns)
        if has_facade and has_internal:
            issues.append(
                f"[[interfaces]] for {product_label} mixes facade/presentation exposes with "
                "internal exposes — split into separate blocks or remove the facade patterns "
                "from the legacy leak block"
            )

        for pattern in expose_patterns:
            normalized = pattern.replace("\\", "")
            if re.match(r"^backend\.{0,2}\*", normalized):
                issues.append(
                    f"[[interfaces]] for {product_label} has overly broad expose "
                    f"'{pattern}' — enumerate specific submodules instead"
                )

    return issues


def validate_tach_references(tach_content: str) -> list[str]:
    """Validate referential integrity in tach.toml.

    Checks:
      1. Every [[interfaces]] from must reference an existing [[modules]] path.
      2. Every [[modules]] depends_on entry must reference an existing module.
    """
    issues: list[str] = []

    module_paths: set[str] = set()
    for path, _deps in _iter_module_blocks(tach_content):
        module_paths.add(path)

    for _expose, from_patterns in _iter_interface_blocks(tach_content):
        for pattern in from_patterns:
            names = _names_from_pattern(pattern)
            for name in names:
                module_path = f"products.{name}"
                if module_path not in module_paths:
                    issues.append(
                        f"[[interfaces]] references '{module_path}' but no [[modules]] "
                        f"block with that path exists — dangling interface declaration"
                    )

    for path, depends_on in _iter_module_blocks(tach_content):
        for dep in depends_on:
            if dep not in module_paths:
                issues.append(
                    f"[[modules]] '{path}' depends on '{dep}' but no [[modules]] "
                    f"block with that path exists — dangling dependency"
                )

    return issues


def validate_tach_toml(tach_content: str, products_dir: Path) -> list[str]:
    """Run all tach.toml validation checks."""
    issues: list[str] = []
    issues.extend(validate_facade_alternation(tach_content, products_dir))
    issues.extend(validate_interface_blocks(tach_content))
    issues.extend(validate_tach_references(tach_content))
    return issues


# ---------------------------------------------------------------------------
# Check framework
# ---------------------------------------------------------------------------


@dataclass
class CheckContext:
    name: str
    product_dir: Path
    backend_dir: Path
    is_isolated: bool
    structure: dict
    detailed: bool  # True = single-product run, False = --all
    _isolation: IsolationStatus | None = field(default=None, repr=False, compare=False)

    def isolation_status(self) -> IsolationStatus:
        """Memoized isolation seal status, shared across checks within one product run.

        Several checks need it; computing once avoids re-reading tach.toml/pyproject.toml/
        package.json per check (files don't change mid-run).
        """
        if self._isolation is None:
            self._isolation = compute_isolation_status(
                self.name, self.product_dir, self.backend_dir, is_isolated=self.is_isolated
            )
        return self._isolation


@dataclass
class CheckResult:
    lines: list[str] = field(default_factory=list)  # lines printed to stdout
    issues: list[str] = field(default_factory=list)  # blocking issues returned to caller
    warnings: list[str] = field(default_factory=list)  # non-blocking warnings
    file: str | None = None  # file path for GitHub annotations
    skip: bool = False  # silently skip this check


class ProductCheck(ABC):
    label: str
    for_isolated: bool = True
    for_lenient: bool = True

    def should_run(self, ctx: CheckContext) -> bool:
        if ctx.is_isolated and not self.for_isolated:
            return False
        if not ctx.is_isolated and not self.for_lenient:
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
        required_key = "required" if ctx.is_isolated else "required_lenient"
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


def _contract_check_withheld_note(status: IsolationStatus) -> str | None:
    """Why the contract-check skip is correctly withheld for an isolated product.

    Surfaced on a passing single-product lint so a reader sees the decision, not just
    its silent absence. Returns None when there's nothing meaningful to explain.
    """
    if status.deferred_count > 0 and status.has_legacy_leaks:
        return f"legacy interface leaks + {status.deferred_count} presentation bypass(es) still open"
    if status.deferred_count > 0:
        plural = "bypass" if status.deferred_count == 1 else "bypasses"
        return f"{status.deferred_count} presentation {plural} still open (internal seal incomplete)"
    if status.has_legacy_leaks:
        return "legacy interface leak block present (external seal incomplete)"
    if not status.has_real_facade:
        return "facade/api.py is a re-export, not real functions"
    return None


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

        # --- presence checks (legacy leaks exempt from contract-check) ---
        # While a product has deferred presentation-wave ignore_imports entries, its
        # views still bypass the facade and reach internals directly. The skip only
        # re-runs the full suite on facade/presentation changes, so an internals
        # change flowing to HTTP through such a view would be hidden. The skip is the
        # reward for finishing — it can't be enabled until the wave empties them.
        status = ctx.isolation_status()
        needs_contract_check = status.eligible_for_isolated_tests
        required = ["backend:test"] + (["backend:contract-check"] if needs_contract_check else [])
        for script in required:
            if script not in scripts:
                result.lines.append(f"✗ missing '{script}'")
                result.issues.append(
                    f"Product has backend/ but package.json is missing '{script}' script — "
                    "turbo cannot discover this product"
                )

        # --- absence check: must NOT have contract-check when not safe for isolation ---
        if not needs_contract_check and "backend:contract-check" in scripts:
            if status.has_legacy_leaks:
                reason = "has legacy interface leaks (core imports internals directly)"
            elif status.deferred_count > 0:
                plural = "entry" if status.deferred_count == 1 else "entries"
                reason = (
                    f"has {status.deferred_count} deferred presentation-wave ignore_imports {plural} — its "
                    "presentation still bypasses the facade, so finish the presentation wave (empty the "
                    "ignore_imports TODO section) before opting into the skip"
                )
            else:
                reason = "non-isolated product must not have 'backend:contract-check' script"
            result.lines.append("✗ must not have 'backend:contract-check'")
            result.issues.append(
                f"{reason} — remove 'backend:contract-check' from package.json. "
                "turbo-discover uses this to classify products as isolated, which causes "
                "the full Django test suite to be skipped when this product changes"
            )

        # --- surface the withholding decision (single-product view only; keep the CI sweep quiet) ---
        if ctx.detailed and ctx.is_isolated and not needs_contract_check and "backend:contract-check" not in scripts:
            note = _contract_check_withheld_note(status)
            if note:
                result.lines.append(f"ℹ contract-check skip withheld — {note}")

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

    # Directories allowed in backend/ for strict products.
    # Anything else won't be covered by import-linter's wildcard contracts.
    # `templates` is allowed because Django's app_directories loader requires
    # the folder to live at <app>/templates/, and templates aren't Python
    # imports so import-linter contracts don't apply.
    # `admin` is allowed because Django's autodiscover_modules("admin") requires
    # the admin module at <app>.admin — and that module can be a flat `admin.py`
    # or an `admin/` package (both resolve to the same import). The file form is
    # already accepted, so the package form has to be too.
    # `hogql_queries` is the established home for HogQL query runners across
    # products (web_analytics, revenue_analytics, product_analytics), so it is
    # allowed in isolated products too rather than forcing query code into logic/.
    # `temporal` is the established home for Temporal workflow + activity code
    # across products (batch_exports, data_warehouse, tasks, experiments, and
    # others), so it is allowed in isolated products on the same grounds.
    # `sandbox` holds Docker build context (Dockerfiles + helper scripts) for
    # sandboxed execution, not importable Python — its path is referenced by
    # image-build workflows and COPY directives, so it can't follow the
    # Python-package convention and is allowed at backend root.
    _KNOWN_DIRS = {
        "facade",
        "presentation",
        "tasks",
        "tests",
        "test",
        "migrations",
        "management",
        "models",
        "logic",
        "hogql_queries",
        "temporal",
        "sandbox",
        "templates",
        "admin",
        "__pycache__",
    }

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

        # Flag directories not in the canonical structure — these bypass
        # import-linter's wildcard enforcement (presentation/facade/etc.)
        for child in sorted(ctx.backend_dir.iterdir()):
            if child.is_dir() and child.name not in self._KNOWN_DIRS:
                misplaced.append(
                    f"backend/{child.name}/ is not a recognized directory — "
                    "import-linter only enforces canonical paths (presentation, facade, logic, models). "
                    "Move code into an existing directory or update the product structure"
                )

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


class TachCheck(ProductCheck):
    label = "tach boundaries"

    def _has_python_files(self, product_dir: Path) -> bool:
        return any(p for p in product_dir.rglob("*.py") if p.name != "__init__.py")

    def run(self, ctx: CheckContext) -> CheckResult:
        if not self._has_python_files(ctx.product_dir):
            return CheckResult(skip=True)

        module_path = f"products.{ctx.name}"
        tach_block = get_tach_block(module_path)

        if not tach_block:
            return CheckResult(
                lines=["✗ missing from tach.toml"],
                issues=[
                    f"Product has Python files but no [[modules]] entry in tach.toml — "
                    f'add a block with path = "{module_path}"'
                ],
            )

        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        if ctx.is_isolated and not has_tach_interface(ctx.name, tach_content):
            return CheckResult(
                lines=["✗ missing interfaces declaration"],
                issues=[
                    f"Isolated product missing interface definition in tach.toml — "
                    f'add a [[interfaces]] block with from = ["{module_path}"]'
                ],
            )

        if has_legacy_interface_leaks(tach_content, module_path):
            return CheckResult(lines=["⚠ has legacy interface leaks — core bypasses facade (not tested in isolation)"])

        return CheckResult(lines=["✓ ok"])


class IsolationChainCheck(ProductCheck):
    """Validates the isolation prerequisite chain is consistent — and finished.

    The chain: real facade → tach interfaces → contract-check script → narrowed turbo.json.
    Each step requires the previous one, so a product can't claim a CI benefit it hasn't
    earned (the Django suite skipped on changes). The final step also can't be left
    half-wired: once a product is fully sealed and eligible, it must actually turn the skip
    on by narrowing turbo.json inputs — otherwise the contract-check script is inert
    (inputs default to all of backend/, so every change still re-runs the Django suite).
    """

    label = "isolation chain"

    def run(self, ctx: CheckContext) -> CheckResult:
        facade_api = ctx.backend_dir / "facade" / "api.py"
        status = ctx.isolation_status()
        real_facade = status.has_real_facade
        has_tach = status.has_tach_interface
        has_script = status.has_contract_check_script
        has_narrowed = status.has_narrowed_turbo

        result = CheckResult()

        if has_script and not real_facade:
            result.issues.append(
                "has 'backend:contract-check' but facade/api.py has no function definitions — "
                "re-exporting from logic is not a facade. turbo-discover classifies this product "
                "as isolated, which may cause the Django test suite to be skipped on changes"
            )

        if has_script and not has_tach:
            result.issues.append(
                "has 'backend:contract-check' but no tach interfaces — isolation requires tach boundary enforcement"
            )

        if has_narrowed and not has_script:
            result.issues.append(
                "turbo.json narrows contract-check inputs but package.json has no "
                "'backend:contract-check' script — dead config, remove the turbo.json override"
            )

        if has_narrowed and not real_facade:
            result.issues.append(
                "turbo.json narrows contract-check inputs to facade/presentation but "
                "facade/api.py has no function definitions — internal changes won't trigger "
                "Django suite even though the facade boundary isn't real"
            )

        if not has_script and facade_api.exists() and not real_facade:
            result.warnings.append(
                "facade/api.py exists but has no function definitions — "
                "a real facade should convert models to contracts, not just re-export"
            )

        # Earned but not turned on: a fully sealed, eligible product that already carries
        # 'backend:contract-check' (real facade, tach interface, no legacy leaks, presentation
        # wave emptied). Without a turbo.json narrowing its inputs to facade/presentation, that
        # script inherits the root task's all-of-backend inputs, so every internal change still
        # re-runs the full Django suite — the skip is inert. Force the narrowing so READY
        # products land on ON. Gating on has_script keeps this distinct from
        # PackageJsonScriptsCheck, which is what nags a still-eligible product to add the script.
        needs_turn_on = (
            has_script and status.eligible_for_isolated_tests and status.externally_sealed and not has_narrowed
        )
        if needs_turn_on:
            result.issues.append(
                "product is fully sealed and eligible for isolated tests and carries "
                "'backend:contract-check', but turbo.json does not narrow contract-check inputs to "
                "facade/presentation — the skip is inert (every change still re-runs the full Django "
                'suite). Add a turbo.json narrowing inputs to ["backend/facade/**", '
                '"backend/presentation/**"] to turn the skip on'
            )

        # Watching the route registration: routes.py is the product's route-registration entry
        # point (public API surface, imported by core to assemble the router), but it lives at
        # backend/ root — outside the facade/presentation globs. A narrowed product that has one
        # must add it to the inputs, or a routes-only change is invisible to the skip and runs no
        # Django suite. (Mutually exclusive with needs_turn_on, which requires no narrowing.)
        routes_unwatched = (
            has_narrowed and has_routes_module(ctx.backend_dir) and not routes_in_turbo_inputs(ctx.product_dir)
        )
        if routes_unwatched:
            routes_glob = "backend/routes/**" if (ctx.backend_dir / "routes").is_dir() else "backend/routes.py"
            result.issues.append(
                f"turbo.json narrows contract-check inputs but omits {routes_glob} — the routes module is the "
                "product's route-registration entry point (public API surface, imported by core), so a "
                f'routes-only change would skip the Django suite. Add "{routes_glob}" to the contract-check inputs'
            )

        # Watching the permanent-interface exposures: a marked [[interfaces]] block lets core
        # depend on these modules outside the import graph (ClickHouse DDL in the schema registry
        # and frozen migrations). That coupling can't be sealed, so the skip stays sound only if a
        # change to those modules still re-runs the suite — they must be in the contract-check
        # inputs. Mirrors routes_unwatched.
        if has_narrowed and status.uncovered_permanent_exposures:
            globs = ", ".join(f"{m.replace('.', '/')}.py" for m in status.uncovered_permanent_exposures)
            result.issues.append(
                "turbo.json narrows contract-check inputs but omits the permanently-exposed module(s) "
                f"{', '.join(status.uncovered_permanent_exposures)} — core depends on them outside the import "
                "graph (ClickHouse DDL in the schema registry and frozen migrations), so a change to them "
                f"would skip the Django suite. Add the matching input(s) ({globs}) to keep the skip sound"
            )

        # Guarding against marker abuse: the permanent-interface marker is only legitimate for
        # modules core depends on outside the import graph (ClickHouse DDL in a frozen migration or
        # the schema registry). Without this check the marker is mechanically unrestricted — a
        # product could mark backend.models/backend.logic permanent, list it in turbo inputs, and
        # pass the chain. Fires regardless of has_narrowed: the abuse lives in tach.toml itself, not
        # in turbo config, so it must block even before the product narrows.
        if status.unqualified_permanent_exposures:
            modules = ", ".join(status.unqualified_permanent_exposures)
            result.issues.append(
                f"permanent-interface marker covers module(s) {modules}, but they are not imported by any "
                "frozen ClickHouse migration or the ClickHouse schema registry — so they don't qualify as a "
                "permanent interface. Route them through the facade instead (or remove the marker)"
            )

        # Note: a product that has the contract-check script *and* deferred
        # presentation-wave ignore_imports entries is hard-blocked by
        # PackageJsonScriptsCheck — the skip can't be enabled until the wave empties them.

        if result.issues or result.warnings:
            # needs_turn_on and routes_unwatched both point at turbo.json. needs_turn_on can't
            # co-occur with the facade/turbo mismatch issues above (it requires a real facade, a
            # script, and no narrowing). routes_unwatched can co-occur with them (it only needs
            # has_narrowed + a routes module), but turbo.json is still where the routes omission is
            # fixed, so it wins; the co-firing mismatch issues still print in the lint output.
            # An unqualified permanent exposure is a defect in the tach.toml marker itself, so point
            # there; it takes precedence because it's the most fundamental of these issues.
            if status.unqualified_permanent_exposures:
                result.file = "tach.toml"
            elif needs_turn_on or routes_unwatched:
                result.file = f"products/{ctx.name}/turbo.json"
            else:
                result.file = f"products/{ctx.name}/backend/facade/api.py"
        if result.issues:
            result.lines = [f"✗ {len(result.issues)} issue(s)"] + [f"  → {i}" for i in result.issues]
        elif result.warnings:
            result.lines = [f"⚠ {len(result.warnings)} warning(s)"] + [f"  → {w}" for w in result.warnings]
        else:
            result.lines = ["✓ ok"]

        return result


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
    # Per-product exemptions — paths that another workflow targets directly
    # (e.g. ci-backend.yml's Temporal segment) rather than `backend:test`.
    _PRODUCT_SPECIFIC_EXEMPTIONS = {
        # ci-backend.yml "Run Temporal tests" step pytest paths:
        "batch_exports": ("backend/tests/temporal/",),
        "tasks": ("backend/temporal/",),
        "warehouse_sources": ("backend/temporal/",),
        "signals": ("backend/emission/",),
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


CHECKS: list[ProductCheck] = [
    ProductYamlCheck(),
    RequiredRootFilesCheck(),
    PackageJsonScriptsCheck(),
    MisplacedFilesCheck(),
    FileFolderConflictsCheck(),
    TachCheck(),
    IsolationChainCheck(),
    OrphanedTestFilesCheck(),
]
