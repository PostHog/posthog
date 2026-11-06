#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pytest-snob>=0.1.14",
# ]
# ///
"""Select the dagster tests a diff can affect.

Dagster tests reach code exclusively through imports (no URL routing, signals,
or middleware indirection), so the snob import graph is a sound selector here,
unlike for the Django suite. One conservative fallback covers everything the
graph cannot see: when a changed file in a dags tree is a conftest, is not a
Python file, or maps to no test via imports (deleted files, fixture-only
modules), every test in that dags tree is selected.

Modes:
- "full": run the whole suite (infrastructure changed, too many files, or the
  selection covers most of the suite anyway).
- "selected": run only the listed test files, across the suggested shard count.
- "none": no dagster test can be affected; skip the suite. The merge-queue run
  always executes the full suite, so a miss here is caught before merge.

Outputs JSON to stdout. Exit code is 0 even for full mode; the caller treats a
non-zero exit or empty output as full mode (fail-open to today's behavior).
"""

from __future__ import annotations

import os
import re
import ast
import sys
import json
import math
import argparse
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).parent.parent.resolve()
DURATIONS_PATH = REPO_ROOT / ".test_durations"

# Mirrors the pytest invocation in ci-dagster.yml: posthog/dags products/*/dags.
DAGS_TREE_GLOBS = ("posthog/dags", "products/*/dags")
DAGS_TREE_PATTERN = re.compile(r"^(posthog/dags|products/[^/]+/dags)/")

# Changes to these force a full run: they alter how every dagster test executes
# (config, dependencies, the CI environment, or this selector itself).
FULL_RUN_PATTERNS = (
    ".github/workflows/ci-dagster.yml",
    ".github/clickhouse-versions.json",
    ".github/actions/setup-sqlx-cli/",
    "tools/dagster_test_selection.py",
    "tools/test_dagster_test_selection.py",
    "tools/hogli/",
    "tools/hogli-commands/hogli_commands/db_schema.py",
    "tools/hogli-commands/hogli_commands/prechecks.py",
    "tools/hogli-commands/hogli_commands/telemetry_props.py",
    "tools/hogli-commands/hogli_commands/hint_hook.py",
    "tools/hogli-commands/hogli_commands/hints.py",
    "docker-compose",
    "docker/postgres-init-scripts/",
    "rust/persons_migrations/",
    "bin/wait-for-docker",
    "bin/ci-wait-for-docker",
    "hogli.yaml",
    "manage.py",
    "pytest.ini",
    "pyproject.toml",
    "uv.lock",
    "posthog/conftest.py",
    "posthog/test/",
)
ROOT_CONFTEST = "conftest.py"

MAX_CHANGED_FILES = 50

# Matches the ~15 min per shard target in ci-dagster.yml's build-matrix step.
TARGET_SECONDS_PER_SHARD = 900
MAX_SHARDS = 3

# Above this share of the suite's duration, a narrowed run saves nothing over
# the full run and only adds selection risk.
FULL_RUN_DURATION_FRACTION = 0.8


@dataclass(frozen=True)
class Selection:
    mode: str
    tests: list[str] = field(default_factory=list)
    shards: int = 0
    reasons: list[str] = field(default_factory=list)
    fallback_trees: list[str] = field(default_factory=list)
    changed_file_count: int = 0
    selected_seconds: int = 0
    suite_seconds: int = 0

    @property
    def count(self) -> int:
        return len(self.tests)


def dags_trees() -> list[str]:
    trees: list[str] = []
    for pattern in DAGS_TREE_GLOBS:
        if "*" in pattern:
            trees.extend(sorted(str(p.relative_to(REPO_ROOT)) for p in REPO_ROOT.glob(pattern) if p.is_dir()))
        elif (REPO_ROOT / pattern).is_dir():
            trees.append(pattern)
    return trees


def _is_test_file(path: str) -> bool:
    return path.endswith(".py") and PurePosixPath(path).name.startswith("test_")


def test_universe(trees: list[str]) -> set[str]:
    universe: set[str] = set()
    for tree in trees:
        for path in (REPO_ROOT / tree).rglob("test_*.py"):
            universe.add(str(path.relative_to(REPO_ROOT)))
    return universe


def tree_of(path: str) -> str | None:
    """The dags tree a path belongs to, by shape — not by directory existence,
    so files of a deleted tree still classify as dag changes."""
    match = DAGS_TREE_PATTERN.match(path)
    return match.group(1) if match else None


def changed_files_from_git(base_ref: str) -> list[str]:
    # --no-renames splits a rename into a delete + an add, so the removed path
    # stays visible. The tree-fallback and removed-tree guards key on it; with
    # rename detection on, git reports only the destination and both are bypassed.
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def normalize_repo_path(path: str) -> str:
    path_obj = Path(path)
    if path_obj.is_absolute():
        try:
            return str(path_obj.resolve().relative_to(REPO_ROOT.resolve()))
        except ValueError:
            return path
    return str(PurePosixPath(path))


def _module_name(path: str) -> str:
    return path.removesuffix(".py").replace("/", ".")


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")
    return modules


def conftest_dependent_trees(changed_py_files: list[str], trees: list[str]) -> set[str]:
    """Trees whose conftest imports one of the changed modules. Fixtures flow
    through conftests without appearing in any test file's import graph, so
    snob cannot see this reach — e.g. a product conftest importing shared
    fixtures from posthog/dags/tests."""
    changed_modules = {_module_name(path) for path in changed_py_files}
    if not changed_modules:
        return set()
    dependent: set[str] = set()
    for tree in trees:
        for conftest in (REPO_ROOT / tree).rglob("conftest.py"):
            imports = _imported_modules(conftest)
            if imports & changed_modules or any(
                imported.startswith(module + ".") for imported in imports for module in changed_modules
            ):
                dependent.add(tree)
                break
    return dependent


_DYNAMIC_IMPORT_PATTERN = re.compile(r"importlib|__import__")


def dynamic_import_tests(changed_trees: set[str], universe: set[str]) -> set[str]:
    """Test files that load modules dynamically (importlib) see changes the
    static import graph cannot attribute to them, so they run whenever any
    Python file in their tree changes."""
    selected: set[str] = set()
    for test in universe:
        if tree_of(test) not in changed_trees:
            continue
        try:
            if _DYNAMIC_IMPORT_PATTERN.search((REPO_ROOT / test).read_text()):
                selected.add(test)
        except OSError:
            continue
    return selected


def snob_tests(changed_py_files: list[str]) -> set[str]:
    if not changed_py_files:
        return set()
    import snob_lib  # noqa: PLC0415 — resolved by this script's PEP 723 deps, absent in stdlib-only test runs

    return {normalize_repo_path(str(test)) for test in snob_lib.get_tests(changed_py_files)}


def load_durations() -> dict[str, float]:
    if not DURATIONS_PATH.exists():
        return {}
    try:
        raw = json.loads(DURATIONS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(key): float(value) for key, value in raw.items()}


def estimate_seconds(test_files: set[str], durations: dict[str, float]) -> float:
    total = 0.0
    for test_id, duration in durations.items():
        if test_id.split("::", 1)[0] in test_files:
            total += duration
    return total


def removed_tree_reasons(changed_files: list[str], trees: list[str]) -> list[str]:
    """A deleted dags tree leaves no modules for snob to resolve reverse
    dependencies against, so cross-tree import breakage is invisible to
    selection — only a full run can catch it before the merge queue."""
    removed = {tree_of(path) for path in changed_files} - {None} - set(trees)
    return sorted(f"dags tree {tree} no longer exists; forcing a full run" for tree in removed)


def full_run_reasons(changed_files: list[str]) -> list[str]:
    reasons = [
        f"{path} matches full-run pattern {pattern}"
        for path in changed_files
        for pattern in FULL_RUN_PATTERNS
        if pattern in path
    ]
    reasons.extend(f"{path} is the root conftest" for path in changed_files if path == ROOT_CONFTEST)
    if len(changed_files) > MAX_CHANGED_FILES:
        reasons.append(f"too many changed files ({len(changed_files)} > {MAX_CHANGED_FILES})")
    return sorted(reasons)


@dataclass(frozen=True)
class SelectedTests:
    tests: set[str]
    fallback_trees: set[str]


def select_tests(
    changed_files: list[str],
    trees: list[str],
    universe: set[str],
    snob_fn=snob_tests,
) -> SelectedTests:
    selected: set[str] = set()
    fallback_trees: set[str] = set()
    outside_py: list[str] = []
    in_tree_py: list[str] = []
    changed_trees: set[str] = set()

    for path in changed_files:
        tree = tree_of(path)
        if tree is None:
            if path.endswith(".py"):
                outside_py.append(path)
            continue
        if path.endswith(".md"):
            continue
        if not path.endswith(".py"):
            # Snapshots, SQL, and YAML reach tests without imports — run
            # everything in the tree.
            fallback_trees.add(tree)
            changed_trees.add(tree)
            continue
        in_tree_py.append(path)
        changed_trees.add(tree)
        if PurePosixPath(path).name == "conftest.py":
            # Conftest fixtures reach every test in the tree without imports.
            fallback_trees.add(tree)
            continue
        if _is_test_file(path):
            selected.add(path)
            continue
        # Per-file snob calls keep attribution: a changed module no test
        # imports (deleted or fixture-only) falls back to its whole tree.
        covered = snob_fn([path]) & universe
        if covered:
            selected |= covered
        else:
            fallback_trees.add(tree)

    selected |= snob_fn(outside_py) & universe
    fallback_trees |= conftest_dependent_trees(in_tree_py, trees)
    selected |= dynamic_import_tests(changed_trees, universe)
    for tree in fallback_trees:
        selected |= {test for test in universe if test.startswith(tree + "/")}
    selected = {test for test in selected if (REPO_ROOT / test).is_file()}
    return SelectedTests(tests=selected, fallback_trees=fallback_trees)


def shard_count(selected_seconds: float, test_file_count: int) -> int:
    # Never more shards than test files: pytest-split's file granularity would
    # leave a shard with nothing to collect, and pytest exits nonzero on that.
    ceiling = min(MAX_SHARDS, max(1, test_file_count))
    if selected_seconds <= 0:
        return 1
    return min(ceiling, max(1, math.ceil(selected_seconds / TARGET_SECONDS_PER_SHARD)))


def build_selection(changed_files: list[str], snob_fn=snob_tests) -> Selection:
    trees = dags_trees()
    universe = test_universe(trees)
    durations = load_durations()
    suite_seconds = round(estimate_seconds(universe, durations))

    reasons = full_run_reasons(changed_files) + removed_tree_reasons(changed_files, trees)
    if reasons:
        return Selection(
            mode="full",
            reasons=reasons,
            changed_file_count=len(changed_files),
            suite_seconds=suite_seconds,
        )

    picked = select_tests(changed_files, trees, universe, snob_fn=snob_fn)
    selected = picked.tests
    selected_seconds = round(estimate_seconds(selected, durations))

    if not selected:
        return Selection(
            mode="none",
            changed_file_count=len(changed_files),
            suite_seconds=suite_seconds,
        )
    if suite_seconds and selected_seconds >= FULL_RUN_DURATION_FRACTION * suite_seconds:
        return Selection(
            mode="full",
            reasons=[f"selection covers most of the suite ({selected_seconds}s of {suite_seconds}s)"],
            changed_file_count=len(changed_files),
            selected_seconds=selected_seconds,
            suite_seconds=suite_seconds,
        )
    return Selection(
        mode="selected",
        tests=sorted(selected),
        shards=shard_count(selected_seconds, len(selected)),
        fallback_trees=sorted(picked.fallback_trees),
        changed_file_count=len(changed_files),
        selected_seconds=selected_seconds,
        suite_seconds=suite_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="Base ref for git diff, for example origin/master")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    try:
        changed_files = changed_files_from_git(args.base_ref)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"Error: git diff against {args.base_ref!r} failed: {exc.stderr}\n")
        sys.exit(1)

    selection = build_selection(changed_files)
    result = asdict(selection) | {"count": selection.count, "base_ref": args.base_ref}
    sys.stdout.write(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
