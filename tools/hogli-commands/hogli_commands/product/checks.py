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

from .paths import TACH_TOML, get_tach_block
from .scaffold import flatten_structure

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


def _iter_interface_blocks(tach_content: str) -> Iterator[tuple[list[str], list[str]]]:
    """Yield (expose_patterns, from_patterns) for every [[interfaces]] block."""
    for match in re.finditer(r"\[\[interfaces\]\]\s*\n(.*?)(?=\[\[|\Z)", tach_content, re.DOTALL):
        block = match.group(1)
        expose_match = re.search(r"expose\s*=\s*\[(.*?)\]", block, re.DOTALL)
        from_match = re.search(r"from\s*=\s*\[(.*?)\]", block, re.DOTALL)
        if not expose_match or not from_match:
            continue
        expose_patterns = re.findall(r'"(.*?)"', expose_match.group(1))
        from_patterns = re.findall(r'"(.*?)"', from_match.group(1))
        yield expose_patterns, from_patterns


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


def _pattern_targets_public_surface(pattern: str) -> bool:
    """True if a tach expose pattern targets backend.facade or backend.presentation.

    Strips backslashes first so it works on both the on-disk TOML form (`\\.`,
    two literal backslashes) and Python-string fixtures (single backslash).
    """
    normalized = pattern.replace("\\", "")
    return normalized.startswith("backend.facade") or normalized.startswith("backend.presentation")


def has_legacy_interface_leaks(tach_content: str, module_path: str) -> bool:
    """Check if a product has legacy interface leak blocks in tach.toml.

    These are products where core (posthog/ee) still imports internals directly,
    so they can't safely be tested in isolation via contract-check.

    Detected structurally: an [[interfaces]] block whose `from` is exactly this
    module and whose `expose` includes any non-facade/non-presentation pattern.
    """
    for expose_patterns, from_patterns in _iter_interface_blocks(tach_content):
        normalized_from = [p.replace("\\", "") for p in from_patterns]
        if normalized_from != [module_path]:
            continue
        if any(not _pattern_targets_public_surface(p) for p in expose_patterns):
            return True
    return False


def is_isolated_product(backend_dir: Path) -> bool:
    return (backend_dir / "facade" / "contracts.py").exists() or (backend_dir / "facade" / "contracts").exists()


# ---------------------------------------------------------------------------
# Canonical facade alternation validation (global, not per-product)
# ---------------------------------------------------------------------------


def _is_canonical_facade_expose(expose_patterns: list[str]) -> bool:
    """Canonical = every expose pattern targets backend.facade or backend.presentation."""
    if not expose_patterns:
        return False
    return all(_pattern_targets_public_surface(p) for p in expose_patterns)


def _names_from_pattern(pattern: str) -> set[str]:
    """Extract product short names from a tach `from` pattern.

    Handles three forms:
      - "products.experiments"                       -> {"experiments"}
      - "products\\.experiments"                     -> {"experiments"}
      - "products\\.(experiments|mcp_store|...)"     -> {"experiments", "mcp_store", ...}
    """
    # Normalize backslashes — tach regex uses `\.` which appears as `\\.` when
    # read as raw TOML source.
    normalized = pattern.replace("\\", "")
    m = re.match(r"^products\.\(([^)]+)\)$", normalized)
    if m:
        return {n.strip() for n in m.group(1).split("|") if n.strip()}
    m = re.match(r"^products\.([A-Za-z0-9_]+)$", normalized)
    if m:
        return {m.group(1)}
    return set()


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
        from .ast_helpers import has_any_function_defs

        module_path = f"products.{ctx.name}"
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        has_leaks = has_legacy_interface_leaks(tach_content, module_path)

        facade_api = ctx.backend_dir / "facade" / "api.py"
        has_real_facade = facade_api.exists() and has_any_function_defs(facade_api)
        needs_contract_check = ctx.is_isolated and not has_leaks and has_real_facade
        required = ["backend:test"] + (["backend:contract-check"] if needs_contract_check else [])
        for script in required:
            if script not in scripts:
                result.lines.append(f"✗ missing '{script}'")
                result.issues.append(
                    f"Product has backend/ but package.json is missing '{script}' script — "
                    "turbo cannot discover this product"
                )

        # --- absence check: must NOT have contract-check when not safe for isolation ---
        must_not_have_contract_check = not ctx.is_isolated or has_leaks or not has_real_facade
        if must_not_have_contract_check and "backend:contract-check" in scripts:
            if has_leaks:
                reason = "has legacy interface leaks (core imports internals directly)"
            else:
                reason = "non-isolated product must not have 'backend:contract-check' script"
            result.lines.append("✗ must not have 'backend:contract-check'")
            result.issues.append(
                f"{reason} — remove 'backend:contract-check' from package.json. "
                "turbo-discover uses this to classify products as isolated, which causes "
                "the full Django test suite to be skipped when this product changes"
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

    # Directories allowed in backend/ for strict products.
    # Anything else won't be covered by import-linter's wildcard contracts.
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
        #   - "<name>.py" with `can_be_folder: true` (e.g. models.py)
        #   - "<name>/__init__.py"                   (e.g. logic/__init__.py)
        # Any package init file in the canonical structure (facade, presentation,
        # tasks, tests, ...) qualifies; this also catches a stray `tasks.py`
        # next to `tasks/`, which is always a mistake.
        stems: set[str] = set()
        for path, config in flatten_structure(ctx.structure.get("backend_files", {})).items():
            if config.get("can_be_folder", False) and path.endswith(".py"):
                stems.add(path[: -len(".py")])
            elif path.endswith("/__init__.py"):
                stems.add(path[: -len("/__init__.py")])

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

        if ctx.is_isolated and "interfaces" not in tach_block:
            # Check global [[interfaces]] blocks — the product name may appear
            # literally or as part of a regex pattern in a from = [...] field.
            tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
            product_short = ctx.name
            has_global_interface = bool(
                re.search(
                    rf"\[\[interfaces\]\].*?from\s*=\s*\[.*?{re.escape(product_short)}",
                    tach_content,
                    re.DOTALL,
                )
            )
            if not has_global_interface:
                return CheckResult(
                    lines=["✗ missing interfaces declaration"],
                    issues=[
                        f"Isolated product missing interface definition in tach.toml — "
                        f'add a [[interfaces]] block with from = ["{module_path}"]'
                    ],
                )

        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        if has_legacy_interface_leaks(tach_content, module_path):
            return CheckResult(lines=["⚠ has legacy interface leaks — core bypasses facade (not tested in isolation)"])

        return CheckResult(lines=["✓ ok"])


class IsolationChainCheck(ProductCheck):
    """Validates the isolation prerequisite chain is consistent.

    The chain: real facade → tach interfaces → contract-check script → narrowed turbo.json.
    Each step requires the previous one. A product that skips a step gets CI
    benefits it hasn't earned (Django suite skipped on changes).
    """

    label = "isolation chain"

    def _has_contract_check_script(self, product_dir: Path) -> bool:
        package_json = product_dir / "package.json"
        if not package_json.exists():
            return False
        try:
            scripts = json.loads(package_json.read_text()).get("scripts", {})
        except json.JSONDecodeError:
            return False
        return "backend:contract-check" in scripts

    def _has_narrowed_turbo_inputs(self, product_dir: Path) -> bool:
        turbo_json = product_dir / "turbo.json"
        if not turbo_json.exists():
            return False
        try:
            tasks = json.loads(turbo_json.read_text()).get("tasks", {})
        except json.JSONDecodeError:
            return False
        contract_task = tasks.get("backend:contract-check")
        if not contract_task:
            return False
        inputs = contract_task.get("inputs", [])
        return any("facade" in i or "presentation" in i for i in inputs)

    def _has_tach_interfaces(self, name: str) -> bool:
        module_path = f"products.{name}"
        block = get_tach_block(module_path)
        if not block:
            return False
        if "interfaces" in block and "interfaces = []" not in block:
            return True
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        return bool(
            re.search(
                rf"\[\[interfaces\]\].*?from\s*=\s*\[.*?{re.escape(name)}",
                tach_content,
                re.DOTALL,
            )
        )

    def run(self, ctx: CheckContext) -> CheckResult:
        from .ast_helpers import has_any_function_defs

        facade_api = ctx.backend_dir / "facade" / "api.py"
        has_real_facade = facade_api.exists() and has_any_function_defs(facade_api)
        has_tach = self._has_tach_interfaces(ctx.name)
        has_script = self._has_contract_check_script(ctx.product_dir)
        has_narrowed = self._has_narrowed_turbo_inputs(ctx.product_dir)

        result = CheckResult()

        if has_script and not has_real_facade:
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

        if has_narrowed and not has_real_facade:
            result.issues.append(
                "turbo.json narrows contract-check inputs to facade/presentation but "
                "facade/api.py has no function definitions — internal changes won't trigger "
                "Django suite even though the facade boundary isn't real"
            )

        if not has_script and facade_api.exists() and not has_real_facade:
            result.warnings.append(
                "facade/api.py exists but has no function definitions — "
                "a real facade should convert models to contracts, not just re-export"
            )

        if result.issues or result.warnings:
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
    """Validates product.yaml owner slugs against GitHub org teams."""

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
            import os

            if os.environ.get("GITHUB_ACTIONS") == "true":
                return CheckResult(lines=[f"⚠ {fetch_err}, skipping in CI"])
            return CheckResult(
                lines=[f"✗ {fetch_err}"],
                issues=[fetch_err],
                file=f"products/{ctx.name}/product.yaml",
            )

        result = CheckResult(file=f"products/{ctx.name}/product.yaml")

        for owner in owners:
            if isinstance(owner, str) and owner not in gh_teams:
                result.issues.append(
                    f"owner '{owner}' is not a GitHub team in PostHog org — check https://github.com/orgs/PostHog/teams"
                )

        if result.issues:
            result.lines = [f"✗ {len(result.issues)} issue(s)"] + [f"  → {i}" for i in result.issues]
        else:
            result.lines = ["✓ ok"]
        return result


CHECKS: list[ProductCheck] = [
    ProductYamlCheck(),
    ProductYamlOwnersCheck(),
    RequiredRootFilesCheck(),
    PackageJsonScriptsCheck(),
    MisplacedFilesCheck(),
    FileFolderConflictsCheck(),
    TachCheck(),
    IsolationChainCheck(),
]
