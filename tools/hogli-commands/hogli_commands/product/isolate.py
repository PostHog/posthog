"""Mechanical tooling for product isolation migrations: scan and move.

scan — read-only recon for the isolating-product-facade-contracts skill:
classified cross-boundary import map, core-coupling count, strict-lint
preflight, and a thin/thick signal per view module. Emits a human report or a
JSON recipe (the recipe is what makes the migration PR regenerable).

move — the deterministic structural half of the migration: viewset modules
into ``presentation/views/``, ``tasks.py`` into a ``tasks/`` package with
pinned celery task names, level-1 relative imports absolutized, and a
repo-wide dotted-path rewrite that covers imports *and* string references
(``@patch`` mock paths). Word boundaries are enforced in one tested place so
agents don't re-derive them per shell dialect.

The semantic work — contract design, call-site rewrites, thin-vs-thick view
decisions — deliberately stays with the engineer or agent.
"""

from __future__ import annotations

import re
import ast
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .ast_helpers import ast_parse_safe
from .checks import CheckContext, MisplacedFilesCheck, RequiredRootFilesCheck
from .cst_helpers import absolutize_relative_imports
from .paths import PRODUCTS_DIR, REPO_ROOT, load_structure

# ---------------------------------------------------------------------------
# Reference scanning (scan)
# ---------------------------------------------------------------------------

# What each consumer kind maps to in the facade design — mirrored from the
# isolating-product-facade-contracts skill so scan output doubles as the plan.
KIND_GUIDANCE = {
    "model-access": "expose a capability function returning a contract (facade/api.py)",
    "query-runner": "expose a builder plus a class re-export (facade/queries.py) — registry consumers dispatch on class identity",
    "celery-task": "re-export the task object (facade/tasks.py); core beat schedules import it",
    "temporal-wiring": "re-export workflows/activities/metrics/constants (facade/temporal.py)",
    "test-fixture": "use apps.get_model(...) plus a TYPE_CHECKING import, or the facade accessor",
    "string-reference": "dotted path in a string (mock @patch path, config) — must be rewritten when modules move",
    "other-internal": "route through a facade function or re-export",
}


@dataclass
class Reference:
    file: str
    line: int
    module: str
    kind: str
    is_import: bool


def classify_reference(module: str, importer: str) -> str:
    parts = Path(importer).parts
    if any(p in ("test", "tests") for p in parts) or Path(importer).name.startswith("test_"):
        return "test-fixture"
    if ".temporal" in module:
        return "temporal-wiring"
    if module.endswith(".tasks") or ".tasks." in module:
        return "celery-task"
    if module.endswith(".models") or ".models." in module:
        return "model-access"
    if "query_runner" in module or "queries" in module:
        return "query-runner"
    return "other-internal"


def _git_python_files(repo_root: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=repo_root, capture_output=True, text=True, check=True).stdout
    return [repo_root / line for line in out.splitlines() if line]


def scan_references(name: str, files: list[Path], repo_root: Path) -> list[Reference]:
    """Cross-boundary references to the product's internals (non-facade) in Python source.

    Scans only the given files (``git ls-files *.py``), so dotted-path references
    in non-Python files (YAML config, TS) are out of scope; the string-reference
    kind covers ``@patch`` paths and config strings that live *in* Python.
    """
    dotted = re.compile(rf"products\.{re.escape(name)}\.backend(?:\.[\w.]*\w)?")
    import_line = re.compile(rf"^\s*(?:from|import)\s+products\.{re.escape(name)}\.backend")
    own_prefix = f"products/{name}/"
    facade_prefix = f"products.{name}.backend.facade"
    refs: list[Reference] = []
    for path in files:
        rel = str(path.relative_to(repo_root))
        if rel.startswith(own_prefix):
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if f"products.{name}.backend" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in dotted.finditer(line):
                module = match.group(0).rstrip(".")
                if module.startswith(facade_prefix):
                    continue
                is_import = bool(import_line.match(line))
                kind = "string-reference" if not is_import else classify_reference(module, rel)
                refs.append(Reference(file=rel, line=lineno, module=module, kind=kind, is_import=is_import))
    return refs


def core_coupling_count(refs: list[Reference]) -> int:
    """The PR-strategy gate from the skill: internals imports from posthog/ and ee/."""
    return sum(1 for r in refs if r.is_import and (r.file.startswith("posthog/") or r.file.startswith("ee/")))


# ---------------------------------------------------------------------------
# Strict-lint preflight and view-module signals (scan)
# ---------------------------------------------------------------------------


def strict_preflight(name: str) -> list[str]:
    """Run the structural checks as if the product were already isolated.

    `product:lint` flips to strict the moment facade/contracts.py exists; this
    surfaces those demands before the migration starts instead of mid-way.
    """
    product_dir = PRODUCTS_DIR / name
    ctx = CheckContext(
        name=name,
        product_dir=product_dir,
        backend_dir=product_dir / "backend",
        is_isolated=True,
        structure=load_structure(),
        detailed=False,
    )
    issues: list[str] = []
    for check in (RequiredRootFilesCheck(), MisplacedFilesCheck()):
        if check.should_run(ctx):
            issues.extend(check.run(ctx).issues)
    return issues


def _base_names(node: ast.ClassDef) -> list[str]:
    names = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def detect_viewset_modules(backend_dir: Path, include_api: bool = False) -> list[Path]:
    """Modules defining ViewSet subclasses — the move candidates.

    Backend root by default. ``include_api`` also scans the conventional
    ``api/`` subpackage, where many products keep their viewsets instead of at
    root (web_analytics, conversations, endpoints, …).
    """
    search_dirs = [backend_dir]
    if include_api and (backend_dir / "api").is_dir():
        search_dirs.append(backend_dir / "api")
    found = []
    for directory in search_dirs:
        for path in sorted(directory.glob("*.py")):
            if path.name in ("__init__.py", "apps.py", "routes.py"):
                continue
            tree = ast_parse_safe(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(b.endswith("ViewSet") for b in _base_names(node)):
                    found.append(path)
                    break
    return found


def internal_import_count(path: Path, name: str) -> int:
    """How many internals a view module imports — the future allowlist size (thin/thick signal)."""
    pattern = re.compile(rf"^\s*(?:from|import)\s+products\.{re.escape(name)}\.backend\.(?!facade|presentation)[\w.]+")
    relative = re.compile(r"^\s*from\s+\.")
    count = 0
    for line in path.read_text().splitlines():
        if pattern.match(line) or relative.match(line):
            count += 1
    return count


def build_scan_report(name: str, repo_root: Path = REPO_ROOT) -> dict:
    backend_dir = PRODUCTS_DIR / name
    if not (backend_dir / "backend").exists():
        raise ValueError(f"products/{name}/backend does not exist")
    refs = scan_references(name, _git_python_files(repo_root), repo_root)
    by_kind: dict[str, list[dict]] = {}
    for ref in sorted(refs, key=lambda r: (r.kind, r.file, r.line)):
        by_kind.setdefault(ref.kind, []).append(asdict(ref))
    view_modules = detect_viewset_modules(backend_dir / "backend", include_api=True)
    return {
        "product": name,
        "core_coupling_count": core_coupling_count(refs),
        "references_by_kind": by_kind,
        "facade_submodules_needed": sorted(
            {"tasks" for k in by_kind if k == "celery-task"}
            | {"temporal" for k in by_kind if k == "temporal-wiring"}
            | {"queries" for k in by_kind if k == "query-runner"}
        ),
        "strict_lint_preflight": strict_preflight(name),
        "view_modules": [
            {
                "module": v.name,
                "internal_imports": internal_import_count(v, name),
            }
            for v in view_modules
        ],
        "kind_guidance": {k: KIND_GUIDANCE[k] for k in by_kind},
    }


def render_scan_report(report: dict) -> str:
    lines = [f"# Isolation scan: {report['product']}", ""]
    count = report["core_coupling_count"]
    gate = "single PR" if count < 100 else "facade-first PR + team-sliced sweeps"
    lines.append(f"Core-coupling count: {count} -> {gate}")
    lines.append("")
    lines.append("## Cross-boundary references (the sweep checklist)")
    for kind, refs in report["references_by_kind"].items():
        lines.append(f"\n### {kind} ({len(refs)}) — {report['kind_guidance'][kind]}")
        for ref in refs:
            lines.append(f"- {ref['file']}:{ref['line']}  {ref['module']}")
    if report["facade_submodules_needed"]:
        lines.append("\n## Facade submodules to scaffold")
        for sub in report["facade_submodules_needed"]:
            lines.append(f"- facade/{sub}.py")
    lines.append("\n## Strict-lint preflight (fails the moment facade/contracts.py exists)")
    if report["strict_lint_preflight"]:
        lines.extend(f"- {issue}" for issue in report["strict_lint_preflight"])
    else:
        lines.append("- clean")
    lines.append("\n## View modules (thin/thick signal = future ignore_imports entries)")
    if report["view_modules"]:
        for view in report["view_modules"]:
            weight = "thin" if view["internal_imports"] <= 2 else "thick"
            lines.append(f"- {view['module']}: {view['internal_imports']} internal imports ({weight})")
    else:
        lines.append("- none detected (backend root or api/)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Path rewriting and structural moves (move)
# ---------------------------------------------------------------------------


def rewrite_paths(text: str, renames: dict[str, str]) -> str:
    """Rewrite dotted module paths with real word boundaries.

    Covers imports and string references alike: fully qualified dotted paths
    are lexically unambiguous, so a guarded literal match is the boring, safe
    tool. A trailing dot stays valid (``old.Symbol`` -> ``new.Symbol``); a
    trailing identifier character does not (``...api`` must not match
    ``...apps``).
    """
    for old, new in sorted(renames.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(old)}(?![A-Za-z0-9_])")
        text = pattern.sub(new, text)
    return text


def _args_span(text: str, open_idx: int) -> int | None:
    """Index just past the ``)`` that balances the ``(`` at ``text[open_idx]``.

    Counts nesting and skips string literals, so decorator args that contain
    their own parens (``expires=timedelta(hours=1)``) are matched whole instead
    of being truncated at the first ``)``. Returns None if the parens never
    balance.
    """
    depth = 0
    quote: str | None = None
    i = open_idx
    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def pin_task_names(text: str, module_path: str) -> tuple[str, list[str]]:
    """Pin ``@shared_task`` registration names to their pre-move dotted path.

    Moving ``tasks.py`` into a ``tasks/`` package silently renames every task's
    registration path, stranding queued messages at deploy. Tasks that already
    pass ``name=`` are left alone; every decorator that can't be pinned safely
    (unbalanced args, not sitting directly above its ``def``) is reported, so a
    partial failure can't hide behind a sibling that did get pinned.
    """
    warnings: list[str] = []
    def_after = re.compile(r"\s*\ndef (?P<fn>\w+)\(")
    # Rewrite back-to-front so each splice leaves earlier match offsets valid.
    for dec in reversed(list(re.finditer(r"@shared_task\b", text))):
        body_start = dec.end()
        if body_start < len(text) and text[body_start] == "(":
            args_end = _args_span(text, body_start)
            if args_end is None:
                warnings.append("a @shared_task decorator has unbalanced args — pin name= manually")
                continue
            args: str | None = text[body_start:args_end]
        else:
            args_end = body_start
            args = None
        following = def_after.match(text, args_end)
        if following is None:
            warnings.append("a @shared_task decorator is not directly above its def — pin name= manually")
            continue
        if args is not None and "name=" in args:
            continue
        pinned_name = f"{module_path}.{following.group('fn')}"
        if args is None:
            replacement = f'@shared_task(name="{pinned_name}")'
        else:
            inner = args[1:-1].strip()
            joined = f'{inner}, name="{pinned_name}"' if inner else f'name="{pinned_name}"'
            replacement = f"@shared_task({joined})"
        text = text[: dec.start()] + replacement + text[args_end:]
    return text, warnings


def shared_task_names(path: Path) -> list[str]:
    tree = ast_parse_safe(path)
    if tree is None:
        return []
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if (isinstance(target, ast.Name) and target.id == "shared_task") or (
                isinstance(target, ast.Attribute) and target.attr == "shared_task"
            ):
                names.append(node.name)
    return names


def _module_dotted(name: str, rel: Path) -> str:
    """Dotted module path of a backend-relative file.

    ``api/heatmaps_api.py`` -> ``products.<name>.backend.api.heatmaps_api`` — the
    intermediate package matters, so derive from the full relative path, not the stem.

    ``rel`` may also be a directory (the package containing a file). A backend-root
    file has parent ``Path('.')``, whose ``with_suffix`` raises on an empty name —
    that case is just the backend package itself.
    """
    parts = rel.with_suffix("").parts if rel != Path(".") else ()
    return ".".join((f"products.{name}.backend", *parts))


@dataclass
class MovePlan:
    product: str
    view_moves: list[tuple[Path, Path]]
    module_renames: dict[str, str]
    tasks_move: tuple[Path, Path] | None
    serializers_move: tuple[Path, Path] | None = None
    # api/ test subpackages relocate out of the api namespace into the product's
    # own test dir, so they can't ride the api -> presentation.views prefix rename.
    test_moves: list[tuple[Path, Path]] = field(default_factory=list)
    # api/ modules whose stem already exists at presentation/<stem>.py — almost
    # always a compat shim for a module already migrated by hand. Moving it would
    # duplicate the module, so the move refuses until it's resolved (see execute).
    presentation_conflicts: list[Path] = field(default_factory=list)


_TEST_DIRS = ("test", "tests")


def build_move_plan(name: str, views: list[str] | None = None) -> MovePlan:
    backend_dir = PRODUCTS_DIR / name / "backend"
    target_dir = backend_dir / "presentation" / "views"
    view_moves: list[tuple[Path, Path]] = []
    test_moves: list[tuple[Path, Path]] = []
    presentation_conflicts: list[Path] = []
    renames: dict[str, str] = {}

    if views:
        view_paths = [backend_dir / v for v in views]
        missing = [str(p) for p in view_paths if not p.exists()]
        if missing:
            raise ValueError(f"view modules not found: {missing}")
        for p in view_paths:
            view_moves.append((p, target_dir / p.name))
            renames[_module_dotted(name, p.relative_to(backend_dir))] = (
                f"products.{name}.backend.presentation.views.{p.stem}"
            )
    else:
        for p in detect_viewset_modules(backend_dir):
            view_moves.append((p, target_dir / p.name))
            renames[f"products.{name}.backend.{p.stem}"] = f"products.{name}.backend.presentation.views.{p.stem}"
        api_dir = backend_dir / "api"
        if api_dir.is_dir():
            # Relocate the whole api/ subtree, not just its top-level files —
            # production helper subpackages (e.g. destination_tests/) are part of
            # the package's surface and ride the prefix rename with everything
            # else, so one rename (backend.api -> backend.presentation.views)
            # covers them. Test subpackages can't ride it: they leave the api
            # namespace for the product's test dir, so they get their own rename
            # and their relative imports are absolutized at move time.
            tests_target = backend_dir / "tests" / "api"
            presentation_dir = backend_dir / "presentation"
            for p in sorted(api_dir.rglob("*.py")):
                rel = p.relative_to(api_dir)
                if rel.parts[0] in _TEST_DIRS:
                    test_moves.append((p, tests_target / Path(*rel.parts[1:])))
                else:
                    view_moves.append((p, target_dir / rel))
                    # A top-level api module already mirrored at presentation/<stem>.py
                    # is a compat shim for an already-migrated module — moving it would
                    # leave the canonical module and a stray shim side by side. The
                    # package marker is always mirrored, so it is not a conflict.
                    if len(rel.parts) == 1 and p.name != "__init__.py" and (presentation_dir / p.name).is_file():
                        presentation_conflicts.append(p)
            renames[f"products.{name}.backend.api"] = f"products.{name}.backend.presentation.views"
            for tdir in _TEST_DIRS:
                if (api_dir / tdir).is_dir():
                    # Longer prefix, so rewrite_paths applies it before the api ->
                    # presentation.views rename and test paths land in tests/api.
                    renames[f"products.{name}.backend.api.{tdir}"] = f"products.{name}.backend.tests.api"

    serializers_py = backend_dir / "serializers.py"
    serializers_move = None
    if serializers_py.is_file():
        serializers_move = (serializers_py, backend_dir / "presentation" / "serializers.py")
        renames[f"products.{name}.backend.serializers"] = f"products.{name}.backend.presentation.serializers"

    tasks_py = backend_dir / "tasks.py"
    tasks_move = (tasks_py, backend_dir / "tasks" / "tasks.py") if tasks_py.is_file() else None
    return MovePlan(
        product=name,
        view_moves=view_moves,
        module_renames=renames,
        tasks_move=tasks_move,
        serializers_move=serializers_move,
        test_moves=test_moves,
        presentation_conflicts=presentation_conflicts,
    )


_PACKAGE_INIT_DOCSTRINGS = {
    "presentation": '"""HTTP presentation layer of the {name} product (DRF viewsets and serializers)."""\n',
    "views": '"""DRF viewsets for {name} — submodule paths (`backend.presentation.views.*`) are part\nof the shared tach interface for isolated products.\n"""\n',
}


def _git_move_and_absolutize(
    name: str, src: Path, dst: Path, backend_dir: Path, repo_root: Path, log: list[str]
) -> str:
    """git-mv a file into the isolated layout and rewrite its relative imports.

    Relative imports resolve against the file's *original* package, so absolutize
    against that (``backend.api`` for an api/ file, ``backend`` for a root one)
    before the move changes what a leading dot means. Returns the rewritten text.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_package = _module_dotted(name, src.parent.relative_to(backend_dir))
    subprocess.run(["git", "mv", str(src), str(dst)], cwd=repo_root, check=True)
    fixed, warnings = absolutize_relative_imports(dst.read_text(), src_package)
    dst.write_text(fixed)
    log.extend(f"WARNING {dst.relative_to(repo_root)}: {w}" for w in warnings)
    return fixed


def execute_move_plan(plan: MovePlan, repo_root: Path = REPO_ROOT, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    name = plan.product
    backend_dir = PRODUCTS_DIR / name / "backend"

    # The rewrite reads and writes every tracked .py repo-wide, so a modified
    # tracked file anywhere — not just under products/<name> — gets the rewrite
    # mixed into its existing edits and loses the clean `git diff`. Untracked
    # files are never touched (they aren't in `git ls-files`), so ignore them.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty and not dry_run:
        raise ValueError("tracked files have uncommitted changes — commit or stash first so the move stays revertable")

    for src, dst in plan.view_moves:
        log.append(f"move {src.relative_to(repo_root)} -> {dst.relative_to(repo_root)}")
    for src, dst in plan.test_moves:
        log.append(f"move {src.relative_to(repo_root)} -> {dst.relative_to(repo_root)} (test)")
    if plan.serializers_move:
        src, dst = plan.serializers_move
        log.append(f"move {src.relative_to(repo_root)} -> {dst.relative_to(repo_root)}")
    if plan.tasks_move:
        src, dst = plan.tasks_move
        log.append(f"move {src.relative_to(repo_root)} -> {dst.relative_to(repo_root)} (celery names pinned)")
    for old, new in plan.module_renames.items():
        log.append(f"rewrite {old} -> {new} (imports and string references, repo-wide)")
    for p in plan.presentation_conflicts:
        log.append(
            f"BLOCKED {p.relative_to(repo_root)}: presentation/{p.name} already exists "
            "(likely a compat shim for an already-migrated module — resolve by hand)"
        )
    if dry_run:
        return log

    # A test move into an already-populated test dir would clobber a real file
    # (an empty __init__ package marker is the one safe collision — handled below).
    # Fail before mutating anything rather than mid-move.
    collisions = [
        dst
        for src, dst in plan.test_moves
        if dst.exists() and not (src.name == "__init__.py" and dst.name == "__init__.py")
    ]
    if collisions:
        joined = ", ".join(str(c.relative_to(repo_root)) for c in collisions)
        raise ValueError(f"test moves collide with existing files: {joined} — merge them into the test dir by hand")

    # An api module already mirrored under presentation/ is a compat shim for code
    # migrated by hand — moving it would duplicate the module. The right fix is manual
    # (delete the shim, repoint its callers), so refuse before mutating.
    if plan.presentation_conflicts:
        joined = ", ".join(str(p.relative_to(repo_root)) for p in plan.presentation_conflicts)
        raise ValueError(
            f"api modules already mirrored under presentation/ ({joined}) — almost certainly compat "
            "shims for already-migrated modules. Delete each shim and point its callers at the "
            "presentation module, then re-run the move on the rest."
        )

    # __init__ files an api/ subpackage brings with it are move targets — don't
    # pre-create those, or the git mv collides with the scaffolded file.
    move_targets = {dst for _, dst in plan.view_moves}
    if plan.serializers_move:
        move_targets.add(plan.serializers_move[1])

    if plan.view_moves:
        target_dir = backend_dir / "presentation" / "views"
        target_dir.mkdir(parents=True, exist_ok=True)
        for dirname, parent in (("presentation", backend_dir), ("views", backend_dir / "presentation")):
            init = parent / dirname / "__init__.py"
            if not init.exists() and init not in move_targets:
                init.write_text(_PACKAGE_INIT_DOCSTRINGS[dirname].format(name=name))
        for src, dst in plan.view_moves:
            # Nested production subpackages (api/destination_tests/) keep their
            # structure under presentation/views/ — the helper makes the parent.
            fixed = _git_move_and_absolutize(name, src, dst, backend_dir, repo_root, log)
            if "__file__" in fixed:
                # Found the hard way on logs: explain.py resolved its template dir via
                # Path(__file__).parent, which silently points elsewhere after the move.
                log.append(
                    f"WARNING {dst.relative_to(repo_root)}: uses __file__-relative paths — "
                    "re-anchor resource paths for the new module depth"
                )

    for src, dst in plan.test_moves:
        if dst.exists():
            # Pre-flight left only the safe collision: an empty package marker whose
            # destination already exists. The moved one is redundant — drop it.
            subprocess.run(["git", "rm", "-f", "--quiet", str(src)], cwd=repo_root, check=True)
            log.append(f"drop redundant {src.relative_to(repo_root)} ({dst.relative_to(repo_root)} already exists)")
            continue
        # The repo-wide rename carries the now-absolute paths to the moved code.
        _git_move_and_absolutize(name, src, dst, backend_dir, repo_root, log)

    # Clean up api/ only once everything (production + tests) has moved out of it.
    api_dir = backend_dir / "api"
    api_was_moved = any(src.is_relative_to(api_dir) for src, _ in (*plan.view_moves, *plan.test_moves))
    if api_dir.is_dir() and api_was_moved:
        # git mv moves files but leaves the emptied dirs behind, so look for real
        # files left over (a subpackage the move didn't know how to place), not dir
        # entries — an emptied destination_tests/ is not leftover content.
        remaining = sorted(
            str(p.relative_to(api_dir)) for p in api_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
        if remaining:
            log.append(
                f"WARNING {api_dir.relative_to(repo_root)} still holds files after the move ({remaining}) — "
                "relocate them by hand (the move only knows production and test subpackages)"
            )
        else:
            shutil.rmtree(api_dir)
            log.append(f"removed empty {api_dir.relative_to(repo_root)}")

    if plan.serializers_move:
        src, dst = plan.serializers_move
        dst.parent.mkdir(parents=True, exist_ok=True)
        init = backend_dir / "presentation" / "__init__.py"
        if not init.exists():
            init.write_text(_PACKAGE_INIT_DOCSTRINGS["presentation"].format(name=name))
        subprocess.run(["git", "mv", str(src), str(dst)], cwd=repo_root, check=True)
        fixed, warnings = absolutize_relative_imports(dst.read_text(), f"products.{name}.backend")
        dst.write_text(fixed)
        log.extend(f"WARNING {dst.relative_to(repo_root)}: {w}" for w in warnings)

    if plan.tasks_move:
        src, dst = plan.tasks_move
        dst.parent.mkdir(exist_ok=True)
        subprocess.run(["git", "mv", str(src), str(dst)], cwd=repo_root, check=True)
        # Relative imports resolved against backend/ at the old depth — absolutize
        # before the extra package level changes what `.` means, same as the views.
        absolutized, abs_warnings = absolutize_relative_imports(dst.read_text(), f"products.{name}.backend")
        pinned, pin_warnings = pin_task_names(absolutized, f"products.{name}.backend.tasks")
        dst.write_text(pinned)
        log.extend(f"WARNING {dst.relative_to(repo_root)}: {w}" for w in abs_warnings + pin_warnings)
        # Re-export the whole pre-move module surface, not just the task functions:
        # callers reach constants, imported collaborators, and @patch targets through
        # `products.<name>.backend.tasks`, and a task-only re-export breaks them.
        init_lines = [f"from products.{name}.backend.tasks.tasks import *  # noqa: F401,F403"]
        task_names = shared_task_names(dst)
        if task_names:
            init_lines.append(
                f"from products.{name}.backend.tasks.tasks import {', '.join(sorted(task_names))}  # noqa: F401"
            )
        (dst.parent / "__init__.py").write_text("\n".join(init_lines) + "\n")
        # The re-export exposes public names only; a private name (and any @patch
        # target of a module-internal name) reached through the package path breaks
        # once the module is a level deeper. Auto-rewriting these is unsafe — it would
        # corrupt the pinned `name="...tasks.<fn>"` strings — so flag them for manual
        # repointing to products.<name>.backend.tasks.tasks.<name>.
        private_refs = subprocess.run(
            ["git", "grep", "-lE", rf"products\.{re.escape(name)}\.backend\.tasks\._"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if private_refs:
            files = ", ".join(private_refs.splitlines())
            log.append(
                f"WARNING private names of the moved tasks module are referenced through the package path "
                f"({files}) — the re-export can't expose them; repoint these (e.g. @patch targets) to "
                f"products.{name}.backend.tasks.tasks.<name> by hand"
            )

    if plan.module_renames:
        changed = 0
        for path in _git_python_files(repo_root):
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            rewritten = rewrite_paths(text, plan.module_renames)
            if rewritten != text:
                path.write_text(rewritten)
                changed += 1
        log.append(f"rewrote module paths in {changed} files")

    return log
