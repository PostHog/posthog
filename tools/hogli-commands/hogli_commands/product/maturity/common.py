"""Small helpers shared across the dimension scorers."""

from __future__ import annotations

from pathlib import Path


def _has_python_files(product_dir: Path) -> bool:
    return any(p for p in product_dir.rglob("*.py") if p.name != "__init__.py")


def _cap(items: list[str], limit: int) -> list[str]:
    """Truncate a list, appending an ellipsis row when items were dropped."""
    if len(items) <= limit:
        return items
    return [*items[:limit], f"… and {len(items) - limit} more"]
