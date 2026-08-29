"""Orchestrate the dimension scorers across one or all products."""

from __future__ import annotations

import warnings

from ..isolation import compute_isolation_status
from ..paths import PRODUCTS_DIR, REPO_ROOT, TACH_TOML
from ..product_yaml import load_all_product_yamls, load_product_yaml
from . import boundaries, codegen, config, facade, models_dim, presentation, scores


def score_product(
    name: str,
    *,
    assigned_counts: dict[str, int] | None = None,
    inbound_map: dict[str, list[str]] | None = None,
    outbound_map: dict[str, list[str]] | None = None,
    maps_resolved: bool = False,
    tach_content: str | None = None,
    pyproject_text: str | None = None,
    product_yamls: dict[str, dict] | None = None,
) -> scores.ProductScore:
    """Compute all dimension scores for a single product.

    `tach_content`/`pyproject_text` let the --all caller read those repo files once and
    thread them in; a single-product run leaves them None and the helpers read on demand.

    The --all caller scans cross-product imports once and passes the maps with
    `maps_resolved=True` (a map may be None, meaning the scan failed — boundaries scoring
    then shows "scan failed" rather than awarding clean points). A single-product run
    leaves it False, so the scan runs once here.
    """
    if assigned_counts is None:
        assigned_counts = config._load_model_assignments()

    if not maps_resolved:
        built = boundaries._build_cross_import_maps()
        inbound_map = built.inbound if built is not None else None
        outbound_map = built.outbound if built is not None else None

    meta = (product_yamls or {}).get(name) or load_product_yaml(name)
    product_dir = PRODUCTS_DIR / name
    backend_dir = product_dir / "backend"

    raw_owners = meta.get("owners", [])
    owners = raw_owners if isinstance(raw_owners, list) and all(isinstance(o, str) for o in raw_owners) else []

    ps = scores.ProductScore(
        product=name,
        display_name=meta.get("name", "") if isinstance(meta.get("name"), str) else "",
        owners=owners,
    )
    ps.dimensions = [
        models_dim.score_models(name, backend_dir, assigned_counts),
        facade.score_facade(backend_dir),
        presentation.score_presentation(name, backend_dir, pyproject_text),
        boundaries.score_boundaries(name, product_dir, inbound_map, outbound_map, tach_content),
        codegen.score_codegen(product_dir),
    ]
    if backend_dir.exists():
        ps.isolation = compute_isolation_status(
            name, product_dir, backend_dir, tach_content=tach_content, pyproject_text=pyproject_text
        )
    return ps


def score_all_products() -> list[scores.ProductScore]:
    """Score all products, sorted by overall score descending."""
    product_dirs = sorted(
        d.name
        for d in PRODUCTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_")) and d.name != "__pycache__" and (d / "__init__.py").exists()
    )

    assigned_counts = config._load_model_assignments()
    product_yamls = load_all_product_yamls()
    # Read the two repo-level files once and thread them through, instead of letting each
    # of the ~65 products re-read and re-parse them inside the per-product scorers.
    tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    pyproject_text = pyproject_path.read_text() if pyproject_path.exists() else ""
    maps = boundaries._build_cross_import_maps()
    if maps is None:
        warnings.warn("cross-product import scan failed (rg unavailable or timeout)", stacklevel=2)
    # On failure both maps stay None, so boundaries scoring reports "scan failed" instead of
    # awarding clean points — and the scan is not re-run per product.
    inbound_map = maps.inbound if maps is not None else None
    outbound_map = maps.outbound if maps is not None else None

    scores = [
        score_product(
            name,
            assigned_counts=assigned_counts,
            inbound_map=inbound_map,
            outbound_map=outbound_map,
            maps_resolved=True,
            tach_content=tach_content,
            pyproject_text=pyproject_text,
            product_yamls=product_yamls,
        )
        for name in product_dirs
    ]
    scores.sort(key=lambda s: s.overall or -1, reverse=True)
    return scores
