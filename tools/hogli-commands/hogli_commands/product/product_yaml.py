"""Product.yaml loading and parsing."""

from __future__ import annotations

from pathlib import Path

import yaml

from .paths import PRODUCTS_DIR


def parse_product_yaml(path: Path) -> tuple[dict, str | None]:
    """Parse a product.yaml with error reporting.

    Returns (data, error). On success error is None and data is the parsed
    dict. On failure data is {} and error describes what went wrong.
    """
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return {}, f"invalid YAML: {exc}"
    if not isinstance(data, dict):
        return {}, f"must be a YAML mapping, got {type(data).__name__}"
    return data, None


def load_product_yaml(name: str) -> dict:
    """Load a product's product.yaml (best-effort, returns {} if missing or invalid)."""
    path = PRODUCTS_DIR / name / "product.yaml"
    if not path.exists():
        return {}
    data, _err = parse_product_yaml(path)
    return data


def load_all_product_yamls() -> dict[str, dict]:
    """Load product.yaml for all products. Keyed by product directory name."""
    result: dict[str, dict] = {}
    for d in sorted(PRODUCTS_DIR.iterdir()):
        if d.is_dir() and (d / "__init__.py").exists():
            data = load_product_yaml(d.name)
            if data:
                result[d.name] = data
    return result
