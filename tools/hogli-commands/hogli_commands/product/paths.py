"""Shared path constants, structure loader, and helpers used by lint + maturity."""

from __future__ import annotations

from pathlib import Path

import yaml

# product/ -> hogli_commands/ -> hogli-commands/ -> tools/ -> repo root
REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
STRUCTURE_FILE = Path(__file__).parent.parent / "product_structure.yaml"
PRODUCTS_DIR = REPO_ROOT / "products"
TACH_TOML = REPO_ROOT / "tach.toml"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
DJANGO_SETTINGS = REPO_ROOT / "posthog" / "settings" / "web.py"
DB_ROUTING_YAML = PRODUCTS_DIR / "db_routing.yaml"
ISOLATION_BASELINE = PRODUCTS_DIR / "isolation_baseline.txt"


def is_backend_product_dir(d: Path) -> bool:
    """Identify products with backend code that should be linted.

    A `backend/` directory holding at least one `.py` is the load-bearing signal.
    Discovery deliberately does NOT depend on `__init__.py` — that's the file
    we want the lint itself to enforce, so using it as the discovery
    signal would silently drop products that are missing it (the bug
    that let `actions/` slip through for weeks after the model move).

    The `.py` condition is what keeps a deleted product out. Git does not track
    directories, so removing a product leaves its empty `backend/` behind in
    every existing worktree — `agent_platform` and `desktop_recordings` are both
    sitting there today. CI clones fresh and never sees them, so anything that
    only runs in CI is unaffected, but the isolation baseline is generated
    locally and committed, and would carry the ghosts into the repo.

    Frontend-only products (no `backend/`) are skipped — they carry no
    Python that needs `__init__.py`, `apps.py`, `backend:test`, etc.

    `query_performance_ai/` is the one exception today — a local-only
    macOS+Docker dev coordinator that lives under `products/` but isn't
    really a product (no `apps.py`, no `manifest.tsx`, no CI). It's a
    candidate for moving under `tools/`, not for widening discovery here.
    """
    if not d.is_dir() or d.name.startswith((".", "_")):
        return False
    backend = d / "backend"
    return backend.is_dir() and any(backend.rglob("*.py"))


def backend_product_dirs() -> list[Path]:
    """Every product directory with backend code, sorted by name."""
    return sorted(d for d in PRODUCTS_DIR.iterdir() if is_backend_product_dir(d))


def load_structure() -> dict:
    return yaml.safe_load(STRUCTURE_FILE.read_text())


def get_tach_block(module_path: str) -> str:
    """Extract the tach.toml block for a given module path."""
    if not TACH_TOML.exists():
        return ""
    content = TACH_TOML.read_text()
    marker = f'path = "{module_path}"'
    idx = content.find(marker)
    if idx == -1:
        return ""
    block_start = content.rfind("[[modules]]", 0, idx)
    if block_start == -1:
        block_start = idx
    next_block = content.find("[[modules]]", idx + len(marker))
    if next_block == -1:
        return content[block_start:]
    return content[block_start:next_block]


def find_views_path(backend_dir: Path) -> tuple[Path | None, bool]:
    """Find the views file/dir and whether it's at the correct location.

    Returns (path, is_correct_location). Path is None if no views found.
    """
    pres_views = backend_dir / "presentation" / "views.py"
    if pres_views.exists():
        return pres_views, True

    from .ast_helpers import count_viewset_files

    # `hogli product:isolate:move` relocates multi-viewset products into a
    # `presentation/views/` package (one module per resource) rather than a single
    # `presentation/views.py`. Both satisfy the tach `presentation\.views.*` interface,
    # so treat the package form as a correct location too.
    pres_views_pkg = backend_dir / "presentation" / "views"
    if pres_views_pkg.is_dir() and count_viewset_files(pres_views_pkg) > 0:
        return pres_views_pkg, True

    api_dir = backend_dir / "api"
    if api_dir.is_dir() and count_viewset_files(api_dir) > 0:
        return api_dir, False

    for candidate in (
        backend_dir / "api" / "views.py",
        backend_dir / "api.py",
        backend_dir / "views.py",
    ):
        if candidate.exists():
            return candidate, False

    return None, False
