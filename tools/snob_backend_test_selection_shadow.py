#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pytest-snob>=0.1.14",
# ]
# ///
"""Shadow backend test selection: Snob import graph + Django-aware heuristics.

Combines three strategies to maximize recall (no missed tests) while keeping
precision reasonable (don't run everything on every PR):

1. Snob (import graph) — catches direct and transitive import dependencies.
2. AST heuristics — catches Django API-client tests that reach code through
   URL routing, not imports.
3. Django-aware expansion — catches middleware, signal handlers, DB routers,
   model field changes, and other framework-level indirection that neither
   import graphs nor AST heuristics can see.

Validated against pytest-testmon runtime coverage data (PR #56370).
The import graph alone covers ~33% of real test dependencies. The AST
heuristics close the URL-dispatch gap (~4%). Django-aware expansion closes
signals, middleware, and same-app fallback gaps (~12%). The remainder is
migration noise and framework-level indirection covered by FULL_RUN_PATTERNS.

Shadow mode: outputs JSON to stdout, does not affect CI pass/fail.
"""

from __future__ import annotations

import os
import ast
import sys
import json
import argparse
import warnings
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).parent.parent.resolve()
DURATIONS_PATH = REPO_ROOT / ".test_durations"
HIGH_FANOUT_PATH = Path(__file__).parent / "testmon_high_fanout_files.txt"

LOCAL_ROOTS = ("posthog", "ee", "products", "common", "dags")
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put"}
API_CLIENT_IMPORTS = {
    "django.test.Client",
    "django.test.client.Client",
    "rest_framework.test.APIClient",
    "rest_framework.test.APIRequestFactory",
}
API_SURFACE_PARTS = {"api", "presentation", "serializers", "views", "urls"}

# Files/patterns that force a full test run when changed.
FULL_RUN_PATTERNS = (
    # Python infrastructure
    "conftest.py",
    "posthog/settings/",
    "posthog/test/",
    "manage.py",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
    "mypy.ini",
    ".test_durations",
    # CI / Docker infrastructure
    ".github/workflows/ci-backend.yml",
    ".github/clickhouse-versions.json",
    "docker-compose",
    "docker/clickhouse/",
    "bin/wait-for-docker",
    "bin/ci-wait-for-docker",
    # Non-Python files that affect generated Python code or test behavior
    "frontend/src/queries/schema.json",
    "frontend/src/products.json",
    "frontend/public/email/",
    "rust/feature-flags/src/properties/property_models.rs",
    "common/plugin_transpiler/src",
)

# Patterns that indicate "broad API tests needed" but not full suite.
# These are Django infrastructure files reached through settings/framework
# machinery rather than imports — testmon shows they affect many tests.
MIDDLEWARE_PATTERNS = ("middleware",)
DB_ROUTER_PATTERNS = ("db_router", "product_db_config")

# Django signal connection patterns in source code
SIGNAL_CONNECT_NAMES = {
    "pre_save",
    "post_save",
    "pre_delete",
    "post_delete",
    "m2m_changed",
    "pre_init",
    "post_init",
    "pre_migrate",
    "post_migrate",
    "request_started",
    "request_finished",
    "got_request_exception",
}

MAX_CHANGED_FILES = 50


@dataclass(frozen=True)
class TestFeatures:
    path: str
    imports_api_client: bool = False
    calls_http_client: bool = False
    uses_api_url: bool = False
    uses_reverse: bool = False
    uses_temporal: bool = False
    uses_celery: bool = False
    uses_clickhouse: bool = False
    api_tokens: tuple[str, ...] = ()

    @property
    def is_django_api_test(self) -> bool:
        return self.imports_api_client or self.uses_api_url or self.uses_reverse or self.calls_http_client


@dataclass
class AstSelection:
    tests: list[str] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)
    full_run_reasons: list[str] = field(default_factory=list)
    classified_test_count: int = 0


def _is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return path.endswith(".py") and (name.startswith("test_") or name.startswith("eval_"))


def _iter_python_files() -> list[str]:
    files: list[str] = []
    for root in LOCAL_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" not in path.parts:
                files.append(str(path.relative_to(REPO_ROOT)))
    return sorted(files)


def _read_tree(path: str) -> ast.AST | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse((REPO_ROOT / path).read_text(), filename=path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _name_from_node(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_from_node(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _literal_strings(tree: ast.AST) -> set[str]:
    strings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value)
    return strings


def _imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            for alias in node.names:
                imports.add(f"{node.module}.{alias.name}")
    return imports


def _normal_tokens(value: str) -> set[str]:
    tokens = {value}
    tokens.add(value.replace("_", "-"))
    tokens.add(value.replace("-", "_"))
    if value.endswith("s"):
        tokens.add(value[:-1])
    else:
        tokens.add(f"{value}s")
    return {token for token in tokens if len(token) > 2}


def _tokens_from_name(value: str) -> set[str]:
    tokens = set(_normal_tokens(value))
    for part in value.replace("-", "_").split("_"):
        tokens.update(_normal_tokens(part))
    return tokens


def _api_tokens_from_strings(strings: set[str]) -> tuple[str, ...]:
    tokens: set[str] = set()
    for value in strings:
        if "/api/" not in value and not value.startswith("/api"):
            continue
        for part in value.replace("?", "/").replace("&", "/").split("/"):
            clean = part.strip("{}:@?&=").replace("-", "_")
            if clean and clean not in {"api", "projects", "environments", "current", "team_id", "project_id"}:
                tokens.update(_normal_tokens(clean))
    return tuple(sorted(tokens))


def _load_high_fanout_files() -> frozenset[str]:
    """Load the list of files that testmon shows affecting >50% of all tests.

    Generated from testmon runtime coverage data. Any change to these files
    should trigger a full test run because the selector can't narrow down
    which tests are actually affected.
    """
    if not HIGH_FANOUT_PATH.exists():
        return frozenset()
    return frozenset(line.strip() for line in HIGH_FANOUT_PATH.read_text().splitlines() if line.strip())


def _is_signal_handler_file(path: str) -> bool:
    """Detect files that connect Django signals (reached via AppConfig.ready(), not imports)."""
    tree = _read_tree(path)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "connect":
            receiver = _name_from_node(node.value)
            if any(sig in receiver for sig in SIGNAL_CONNECT_NAMES):
                return True
        if isinstance(node, ast.Name) and node.id == "receiver":
            return True
    name = PurePosixPath(path).name
    return "signal" in name


def _is_middleware_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return any(pattern in name for pattern in MIDDLEWARE_PATTERNS)


def _is_db_router_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return any(pattern in name for pattern in DB_ROUTER_PATTERNS)


def _django_app_for_path(path: str) -> str | None:
    """Return the Django app directory for a file path.

    For products: products/<name>/backend/
    For posthog: posthog/<subpackage>/
    For ee: ee/<subpackage>/
    """
    parts = PurePosixPath(path).parts
    if parts[0] == "products" and len(parts) >= 3:
        return str(PurePosixPath(*parts[:3]))
    if parts[0] in ("posthog", "ee") and len(parts) >= 2:
        return str(PurePosixPath(*parts[:2]))
    return None


def _find_tests_in_app(app_dir: str, all_test_files: set[str]) -> set[str]:
    """Find all test files belonging to the same Django app."""
    prefix = app_dir + "/" if not app_dir.endswith("/") else app_dir
    return {f for f in all_test_files if f.startswith(prefix)}


def classify_test_file(path: str) -> TestFeatures:
    tree = _read_tree(path)
    if tree is None:
        return TestFeatures(path=path)

    strings = _literal_strings(tree)
    imports = _imports(tree)
    calls_http_client = False
    uses_reverse = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = _name_from_node(node.func)
        if function_name.endswith(".reverse") or function_name == "reverse":
            uses_reverse = True
        if isinstance(node.func, ast.Attribute) and node.func.attr in HTTP_METHODS:
            receiver = _name_from_node(node.func.value)
            if receiver.endswith("client") or ".client" in receiver:
                calls_http_client = True

    imports_api_client = bool(imports & API_CLIENT_IMPORTS)
    uses_api_url = any("/api/" in value or value.startswith("/api") for value in strings)
    lower_imports = " ".join(sorted(imports)).lower()
    lower_path = path.lower()

    api_tokens = set(_api_tokens_from_strings(strings))
    if path.startswith("posthog/api/test/"):
        api_tokens.update(_tokens_from_name(PurePosixPath(path).stem.removeprefix("test_")))

    return TestFeatures(
        path=path,
        imports_api_client=imports_api_client,
        calls_http_client=calls_http_client,
        uses_api_url=uses_api_url,
        uses_reverse=uses_reverse,
        uses_temporal="temporal" in lower_path or "temporalio" in lower_imports,
        uses_celery="celery" in lower_path or "celery" in lower_imports,
        uses_clickhouse="clickhouse" in lower_path or "clickhouse" in lower_imports,
        api_tokens=tuple(sorted(api_tokens)),
    )


def classify_tests() -> dict[str, TestFeatures]:
    return {path: classify_test_file(path) for path in _iter_python_files() if _is_test_file(path)}


def changed_files_from_git(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
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


def _product_name(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if len(parts) >= 3 and parts[0] == "products":
        return parts[1]
    return None


def _is_api_surface_change(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if path.startswith("posthog/api/"):
        return True
    if len(parts) >= 4 and parts[0] == "products" and parts[2] == "backend":
        return bool(set(parts[3:]) & API_SURFACE_PARTS)
    return False


def _tokens_for_changed_file(path: str) -> set[str]:
    pure = PurePosixPath(path)
    tokens: set[str] = set()
    tokens.update(_tokens_from_name(pure.stem.removeprefix("test_")))
    product = _product_name(path)
    if product:
        tokens.update(_normal_tokens(product))
    return tokens


def _candidate_conventional_tests(path: str) -> list[str]:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return []

    test_name = f"test_{pure.stem}.py"
    candidates = [
        pure.parent / test_name,
        pure.parent / "test" / test_name,
        pure.parent / "tests" / test_name,
    ]

    product = _product_name(path)
    if product:
        candidates.extend(
            [
                PurePosixPath("products") / product / "backend" / "test" / test_name,
                PurePosixPath("products") / product / "backend" / "tests" / test_name,
            ]
        )

    return [str(candidate) for candidate in candidates if (REPO_ROOT / candidate).is_file()]


def _add_group(groups: dict[str, set[str]], name: str, tests: list[str] | set[str]) -> None:
    if not tests:
        return
    groups.setdefault(name, set()).update(tests)


def ast_select_tests(changed_files: list[str], features_by_path: dict[str, TestFeatures]) -> AstSelection:
    groups: dict[str, set[str]] = {}
    full_run_reasons: list[str] = []
    all_test_files = set(features_by_path.keys())

    # ── 1. Changed test files themselves ─────────────────────────────
    changed_tests = [path for path in changed_files if _is_test_file(path)]
    _add_group(groups, "changed_tests", changed_tests)

    # ── 2. Conventional test neighbors (test_<name>.py next to <name>.py) ─
    conventional: set[str] = set()
    for path in changed_files:
        conventional.update(_candidate_conventional_tests(path))
    _add_group(groups, "conventional_neighbors", conventional)

    # ── 3. Full-run pattern detection + API surface classification ───
    product_api_changes: dict[str, set[str]] = {}
    posthog_api_tokens: set[str] = set()

    changed_prod_files = [p for p in changed_files if not _is_test_file(p) and p.endswith(".py")]
    high_fanout = _load_high_fanout_files()

    for path in changed_files:
        if not _is_test_file(path):
            for pattern in FULL_RUN_PATTERNS:
                if pattern in path:
                    full_run_reasons.append(f"{path} matches full-run pattern {pattern}")
                    break
            if path in high_fanout:
                full_run_reasons.append(f"{path} is a high-fanout file (testmon: >50% of tests)")

        if not _is_api_surface_change(path):
            continue

        product = _product_name(path)
        if product:
            product_api_changes.setdefault(product, set()).update(_tokens_for_changed_file(path))
        else:
            posthog_api_tokens.update(_tokens_for_changed_file(path))

    # Too many changed files — signal that full run is warranted
    if len(changed_prod_files) > MAX_CHANGED_FILES:
        full_run_reasons.append(f"too many changed files ({len(changed_prod_files)} > {MAX_CHANGED_FILES})")

    # ── 4. Product API client tests (URL dispatch heuristic) ───────���─
    for product, tokens in sorted(product_api_changes.items()):
        product_prefix = f"products/{product}/"
        product_tests = [
            path
            for path, features in features_by_path.items()
            if path.startswith(product_prefix) and features.is_django_api_test
        ]
        _add_group(groups, f"product_api_client:{product}", product_tests)

        token_tests = [
            path
            for path, features in features_by_path.items()
            if path.startswith(product_prefix) and set(features.api_tokens).intersection(tokens)
        ]
        _add_group(groups, f"product_api_route_tokens:{product}", token_tests)

    if posthog_api_tokens:
        api_tests = [
            path
            for path, features in features_by_path.items()
            if path.startswith("posthog/api/test/") and features.is_django_api_test
        ]
        token_tests = [
            path
            for path, features in features_by_path.items()
            if path.startswith("posthog/api/test/") and set(features.api_tokens).intersection(posthog_api_tokens)
        ]
        _add_group(groups, "posthog_api_route_tokens", token_tests)
        if not token_tests:
            _add_group(groups, "posthog_api_client_fallback", api_tests)

    # ── 5. Temporal / ClickHouse broad matching ──────────────────────
    if any("temporal" in path for path in changed_files):
        _add_group(
            groups,
            "temporal",
            {path for path, features in features_by_path.items() if features.uses_temporal},
        )

    if any("clickhouse" in path for path in changed_files):
        _add_group(
            groups,
            "clickhouse",
            {path for path, features in features_by_path.items() if features.uses_clickhouse},
        )

    # ── 6. Signal handler expansion ──────────────────────────────────
    # Testmon shows signal handlers affect hundreds of tests through
    # Django's dispatch mechanism. When a signal handler file changes,
    # include all API-client tests in the same app (the models emitting
    # signals are exercised through API endpoints).
    for path in changed_prod_files:
        if _is_signal_handler_file(path):
            app = _django_app_for_path(path)
            if app:
                app_tests = _find_tests_in_app(app, all_test_files)
                _add_group(groups, f"signal_handler_app:{app}", app_tests)
            # Signal handlers often affect tests across apps too — include
            # all API-client tests as a conservative fallback
            api_client_tests = {p for p, f in features_by_path.items() if f.is_django_api_test}
            _add_group(groups, "signal_handler_api_tests", api_client_tests)

    # ── 7. Middleware expansion ───────────────────────────────────────
    # Middleware runs on every request. If changed, include all tests
    # that make HTTP requests (API-client tests).
    if any(_is_middleware_file(path) for path in changed_prod_files):
        api_client_tests = {p for p, f in features_by_path.items() if f.is_django_api_test}
        _add_group(groups, "middleware_api_tests", api_client_tests)

    # ── 8. DB router expansion ───────────────────────────────────────
    # DB routers affect query routing for every ORM operation. Testmon
    # shows product_db_router.py affects 20k tests. Conservative: include
    # all API-client tests.
    if any(_is_db_router_file(path) for path in changed_prod_files):
        api_client_tests = {p for p, f in features_by_path.items() if f.is_django_api_test}
        _add_group(groups, "db_router_api_tests", api_client_tests)

    # ── 9. Same-app fallback ─────────────────────────────────────────
    # For any changed production file, include all tests in the same
    # Django app. This catches model field changes, admin changes, and
    # other intra-app dependencies that the import graph misses.
    for path in changed_prod_files:
        if _is_test_file(path):
            continue
        app = _django_app_for_path(path)
        if app:
            app_tests = _find_tests_in_app(app, all_test_files)
            if app_tests:
                _add_group(groups, f"same_app:{app}", app_tests)

    sorted_groups = {name: sorted(tests) for name, tests in sorted(groups.items())}
    all_tests = sorted({test for tests in sorted_groups.values() for test in tests})
    return AstSelection(
        tests=all_tests,
        groups=sorted_groups,
        full_run_reasons=sorted(full_run_reasons),
        classified_test_count=len(features_by_path),
    )


def snob_select_tests(changed_files: list[str]) -> dict[str, object]:
    changed_py_files = [path for path in changed_files if path.endswith(".py")]
    if not changed_py_files:
        return {"status": "ok", "tests": [], "count": 0}

    try:
        import snob_lib
    except ImportError as exc:
        return {"status": "error", "error": f"could not import snob_lib: {exc}", "tests": [], "count": 0}

    try:
        tests = sorted(normalize_repo_path(str(test)) for test in snob_lib.get_tests(changed_py_files))
    except Exception as exc:
        return {"status": "error", "error": f"snob_lib.get_tests failed: {exc}", "tests": [], "count": 0}

    return {"status": "ok", "tests": tests, "count": len(tests)}


def load_durations() -> dict[str, float]:
    if not DURATIONS_PATH.exists():
        return {}
    try:
        raw = json.loads(DURATIONS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(key): float(value) for key, value in raw.items()}


def estimate_duration(test_files: list[str], durations: dict[str, float]) -> float:
    test_file_set = set(test_files)
    total = 0.0
    for test_id, duration in durations.items():
        file_part = test_id.split("::", 1)[0]
        if file_part in test_file_set:
            total += duration
    return total


def build_result(base_ref: str) -> dict[str, object]:
    os.chdir(REPO_ROOT)
    changed_files = changed_files_from_git(base_ref)
    features_by_path = classify_tests()
    ast_selection = ast_select_tests(changed_files, features_by_path)
    snob_selection = snob_select_tests(changed_files)

    snob_tests = [str(test) for test in snob_selection.get("tests", [])]
    combined_tests = sorted(set(snob_tests) | set(ast_selection.tests))

    durations = load_durations()
    return {
        "mode": "shadow",
        "base_ref": base_ref,
        "changed_files": changed_files,
        "changed_file_count": len(changed_files),
        "snob": snob_selection,
        "ast": asdict(ast_selection),
        "combined": {
            "tests": combined_tests,
            "count": len(combined_tests),
            "duration_seconds": round(estimate_duration(combined_tests, durations)),
        },
        "durations": {
            "snob_seconds": round(estimate_duration(snob_tests, durations)),
            "ast_seconds": round(estimate_duration(ast_selection.tests, durations)),
            "total_seconds": round(sum(durations.values())),
        },
    }


def format_summary(result: dict[str, object]) -> str:
    snob = result["snob"]
    ast_data = result["ast"]
    combined = result["combined"]
    durations = result["durations"]

    lines = [
        "## Shadow test selection",
        "",
        "Shadow-only. Compares Snob's import-graph selection with PostHog-specific AST groups for API-client and other non-import-shaped tests.",
        "",
        "| Metric | Count | Est. duration |",
        "|---|---:|---:|",
        f"| Changed files | {result['changed_file_count']} | - |",
        f"| Snob-selected tests | {snob['count']} | {durations['snob_seconds']}s |",
        f"| AST-selected tests | {len(ast_data['tests'])} | {durations['ast_seconds']}s |",
        f"| Combined unique tests | {combined['count']} | {combined['duration_seconds']}s |",
        f"| Full duration data | - | {durations['total_seconds']}s |",
        "",
        "| AST group | Test files |",
        "|---|---:|",
    ]
    groups = ast_data.get("groups") or {}
    if groups:
        lines.extend(f"| `{name}` | {len(tests)} |" for name, tests in groups.items())
    else:
        lines.append("| none | 0 |")

    if snob.get("status") != "ok":
        lines += ["", f"**Snob error:** {snob.get('error', 'unknown')}"]

    full_run_reasons = ast_data.get("full_run_reasons") or []
    if full_run_reasons:
        lines += ["", "### Full-run signals", ""]
        lines.extend(f"- {reason}" for reason in full_run_reasons)

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="Base ref for git diff, for example origin/master")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument(
        "--summary-path",
        help="Append a Markdown summary to this file (e.g. $GITHUB_STEP_SUMMARY)",
    )
    args = parser.parse_args()

    try:
        result = build_result(args.base_ref)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"Error: git diff against {args.base_ref!r} failed: {exc.stderr}\n")
        sys.exit(1)

    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(result, indent=indent, sort_keys=True) + "\n")

    if args.summary_path:
        with Path(args.summary_path).expanduser().open("a") as fh:
            fh.write(format_summary(result))


if __name__ == "__main__":
    main()
