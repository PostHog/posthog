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
