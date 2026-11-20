"""Shared path constants, structure loader, and helpers used by lint + maturity."""

from __future__ import annotations

from pathlib import Path

import yaml

# product/ -> hogli_commands/ -> hogli-commands/ -> tools/ -> repo root
REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
STRUCTURE_FILE = Path(__file__).parent.parent / "product_structure.yaml"
# The repo roots that hold first-party Python. crossings.py scans them; reverse_accessors.py
# prefix-matches modules against them; the capture scripts in
# posthog/test/repo_invariants/test_startup_import_budget.py carry their own copies.
FIRST_PARTY_ROOTS: tuple[str, ...] = ("posthog", "ee", "products", "common")

PRODUCTS_DIR = REPO_ROOT / "products"
TACH_TOML = REPO_ROOT / "tach.toml"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
DJANGO_SETTINGS = REPO_ROOT / "posthog" / "settings" / "web.py"
DB_ROUTING_YAML = PRODUCTS_DIR / "db_routing.yaml"


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
    only runs in CI is unaffected, but a local `product:lint --all` would fail
    on them.

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
