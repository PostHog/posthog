"""Product maturity scoring and report generation.

Scores each product across five actionable dimensions that map to the
sequential work a team does when isolating their product:

  1. Models     — move models into products/
  2. Facade     — add contracts.py + facade/api.py + logic.py
  3. Presentation — views through facade, serializers on contracts
  4. Boundaries — tach interfaces + fix cross-product imports
  5. Codegen    — schema annotations, generated TS client adoption

Run from repo root:
    bin/hogli product:maturity          # single product detail
    bin/hogli product:maturity --all    # ranked report of all products
"""

from __future__ import annotations

import re
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .ast_helpers import (
    count_direct_orm_queries,
    get_cross_product_internal_imports,
    get_frozen_dataclass_names,
    get_model_names,
    get_orm_bound_serializer_names,
    get_public_function_names,
    has_any_function_defs,
    imports_any,
    view_facade_usage,
)
from .paths import PRODUCTS_DIR, REPO_ROOT, TACH_TOML, find_views_path, get_tach_block
from .product_yaml import load_all_product_yamls, load_product_yaml
from .ts_helpers import codegen_adoption, codegen_call_sites

# ---------------------------------------------------------------------------
# Config loading (best-effort from migration_config.json)
# ---------------------------------------------------------------------------

_MIGRATION_CONFIG = (
    Path(__file__).parent.parent.parent.parent
    / ".agents"
    / "skills"
    / "product-model-migration"
    / "migration_config.json"
)
_SKILL_DIR_CONFIG = Path.home() / ".claude" / "skills" / "product-model-migration" / "migration_config.json"


def _load_migration_config() -> dict:
    """Load migration_config.json (best-effort)."""
    for config_path in (_MIGRATION_CONFIG, _SKILL_DIR_CONFIG):
        if config_path.exists():
            try:
                return json.loads(config_path.read_text())
            except (json.JSONDecodeError, KeyError):
                continue
    return {}


def _load_model_assignments() -> dict[str, int]:
    """Load product -> count of models still to move from migration_config.json.

    Only counts entries that are not yet done — done/skip entries have already
    been moved and their models live in products/.
    """
    config = _load_migration_config()
    counts: dict[str, int] = {}
    for entry in config.get("migrations", []):
        status = entry.get("status", "")
        if status in ("done", "skip"):
            continue
        name = entry["name"]
        n = len(entry.get("model_names", [])) + len(entry.get("ee_models", []))
        if n > 0:
            counts[name] = n
    return counts


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    name: str
    score: int  # 0-100
    detail: str  # human-readable explanation
    applicable: bool = True  # False = dimension doesn't apply to this product


@dataclass
class ProductScore:
    product: str
    display_name: str = ""
    owners: list[str] = field(default_factory=list)
    dimensions: list[DimensionScore] = field(default_factory=list)

    @property
    def overall(self) -> int | None:
        applicable = [d for d in self.dimensions if d.applicable]
        if not applicable:
            return None
        return round(sum(d.score for d in applicable) / len(applicable))

    @property
    def dimension_map(self) -> dict[str, DimensionScore]:
        return {d.name: d for d in self.dimensions}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_python_files(product_dir: Path) -> bool:
    return any(p for p in product_dir.rglob("*.py") if p.name != "__init__.py")


def _count_tach_depends_on(block: str) -> tuple[int, list[str]]:
    """Count non-baseline depends_on entries in a tach block.

    Baseline dependencies (posthog, ee) are expected and don't count.
    Cross-product dependencies are the coupling signal.
    """
    baseline = {"posthog", "ee"}
    deps: list[str] = []
    in_depends = False
    for line in block.split("\n"):
        stripped = line.strip()
        if stripped.startswith("depends_on"):
            if "[" in stripped and "]" in stripped:
                for dep in re.findall(r'"([^"]+)"', stripped):
                    if dep not in baseline:
                        deps.append(dep)
                break
            in_depends = True
            continue
        if in_depends:
            if stripped == "]":
                break
            dep = stripped.strip('"').strip(",").strip('"')
            if dep and dep not in baseline:
                deps.append(dep)
    return len(deps), deps


# ---------------------------------------------------------------------------
# Dimension 1: Models
# ---------------------------------------------------------------------------


def score_models(name: str, backend_dir: Path, assigned_model_counts: dict[str, int]) -> DimensionScore:
    """Are models in products/ or still in posthog/models/?

    100 = all models in products/backend/
    0   = all models still in posthog/models/ or ee/models/
    """
    models_in_product = get_model_names(backend_dir)
    still_to_move = assigned_model_counts.get(name, 0)

    total = len(models_in_product) + still_to_move
    if total == 0:
        return DimensionScore("models", 0, "no models", applicable=False)

    pct = round(100 * len(models_in_product) / total)
    if still_to_move > 0:
        detail = f"{len(models_in_product)}/{total} in product ({still_to_move} to move)"
    else:
        detail = f"{len(models_in_product)}/{total} in product"
    return DimensionScore("models", pct, detail)


# ---------------------------------------------------------------------------
# Dimension 2: Facade layer
# ---------------------------------------------------------------------------


def score_facade(backend_dir: Path) -> DimensionScore:
    """Facade + contracts + logic separation.

    Scores whether the facade layer is real or just scaffolding.
    A stub facade (1 method when the product has dozens of endpoints) shouldn't
    score high.

    Points breakdown (100 total):
      contracts.py exists + pure + non-empty: 15
      facade/api.py exists + pure:            15
      facade has 3+ public methods:           15  (real surface, not a stub)
      logic.py exists:                        15
      views exist inside the product:         20  (facade is pointless if views
                                                   are still in posthog/ee)
      views use the facade:                   20
    """
    has_backend = backend_dir.exists() and _has_python_files(backend_dir)
    if not has_backend:
        return DimensionScore("facade", 0, "no backend", applicable=False)

    model_names = get_model_names(backend_dir)
    views_path, _ = find_views_path(backend_dir)
    if not model_names and not views_path and not (backend_dir / "facade").exists():
        return DimensionScore("facade", 0, "no models or views", applicable=False)

    score = 0
    parts = []

    # Contracts
    contracts_path = backend_dir / "facade" / "contracts.py"
    if contracts_path.exists():
        impure = imports_any(contracts_path, ["django", "rest_framework"])
        dc_names = get_frozen_dataclass_names(contracts_path)
        if dc_names and not impure:
            score += 15
            parts.append(f"contracts ({len(dc_names)} dataclasses)")
        elif dc_names:
            score += 5
            parts.append(f"contracts ({len(dc_names)}, impure)")
        else:
            parts.append("contracts (empty)")
    else:
        parts.append("no contracts")

    # Facade — must have actual function definitions, not just re-exports
    facade_path = backend_dir / "facade" / "api.py"
    real_facade = False
    if facade_path.exists():
        real_facade = has_any_function_defs(facade_path)
        if not real_facade:
            parts.append("facade (re-export only)")
        else:
            impure = imports_any(facade_path, ["rest_framework"])
            fn_names = get_public_function_names(facade_path)
            if not impure:
                score += 15
            else:
                score += 5
                parts.append("facade (impure)")

            if len(fn_names) >= 3:
                score += 15
                parts.append(f"facade ({len(fn_names)} methods)")
            elif fn_names:
                score += 5
                parts.append(f"facade (stub, {len(fn_names)} method)")
    else:
        parts.append("no facade")

    # Logic
    has_logic = (backend_dir / "logic.py").exists() or (backend_dir / "logic").is_dir()
    if has_logic:
        score += 15
        parts.append("logic")
    else:
        parts.append("no logic")

    # Views inside product + using facade
    # "uses facade" only counts when the facade is real — importing a
    # re-export passthrough isn't meaningful isolation
    if views_path is not None:
        score += 20
        uses_facade, _ = view_facade_usage(views_path)
        if uses_facade and real_facade:
            score += 20
            parts.append("views use facade")
        elif uses_facade:
            parts.append("views import facade (but facade is fake)")
        else:
            parts.append("views skip facade")
    else:
        parts.append("views not in product")

    return DimensionScore("facade", score, ", ".join(parts))


# ---------------------------------------------------------------------------
# Dimension 3: Presentation
# ---------------------------------------------------------------------------


def score_presentation(backend_dir: Path) -> DimensionScore:
    """Views through facade, serializers on contracts.

    Points breakdown (100 total):
      views at correct location (presentation/):  25
      views use facade:                           25
      no direct ORM in views:                     25
      serializers not ORM-bound:                  25
    """
    views_path, correct_location = find_views_path(backend_dir)

    if views_path is None:
        model_names = get_model_names(backend_dir)
        if not model_names:
            return DimensionScore("presentation", 0, "no views", applicable=False)
        return DimensionScore("presentation", 0, "views not in product")

    score = 0
    parts = []

    if correct_location:
        score += 25
        parts.append("correct location")
    else:
        parts.append(f"at {views_path.relative_to(backend_dir)}")

    uses_facade, _ = view_facade_usage(views_path)
    orm_queries = count_direct_orm_queries(views_path)

    # Check if the facade is real (has function definitions, not re-exports)
    facade_api = backend_dir / "facade" / "api.py"
    real_facade = facade_api.exists() and has_any_function_defs(facade_api)

    if uses_facade and real_facade:
        score += 25
        parts.append("uses facade")
    elif uses_facade:
        parts.append("imports facade (but facade is fake)")
    else:
        parts.append("no facade usage")

    if orm_queries == 0:
        score += 25
        parts.append("no direct ORM")
    else:
        parts.append(f"{orm_queries} .objects calls")

    # Serializers — check canonical then legacy location
    serializers_path = backend_dir / "presentation" / "serializers.py"
    if not serializers_path.exists():
        serializers_path = backend_dir / "api" / "serializers.py"
    if serializers_path.exists():
        orm_bound = get_orm_bound_serializer_names(serializers_path)
        if not orm_bound:
            score += 25
            parts.append("serializers clean")
        else:
            parts.append(f"{len(orm_bound)} ORM-bound serializers")
    else:
        score += 25
        parts.append("no serializers (ok)")

    return DimensionScore("presentation", score, ", ".join(parts))


# ---------------------------------------------------------------------------
# Dimension 4: Boundaries
# ---------------------------------------------------------------------------


def _build_inbound_violation_map() -> dict[str, int] | None:
    """Build a map of product_name -> inbound violation count for ALL products.

    Single rg pass across the repo, then distributes results. Much faster
    than running rg per-product. Returns None if the scan fails (rg missing
    or timeout) so callers can distinguish "no violations" from "scan failed".
    """
    try:
        result = subprocess.run(
            ["rg", "-n", "--type", "py", r"(?:from|import)\s+products\.\w+\.backend\.", str(REPO_ROOT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    counts: dict[str, int] = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        colon_idx = line.find(":", 1)
        if colon_idx == -1:
            continue
        colon2_idx = line.find(":", colon_idx + 1)
        if colon2_idx == -1:
            continue
        file_path = line[:colon_idx]
        import_text = line[colon2_idx + 1 :].strip()

        # Extract which product is being imported (handles both from/import style)
        match = re.search(r"products\.(\w+)\.backend\.", import_text)
        if not match:
            continue
        product_name = match.group(1)

        # Skip files inside the product itself
        if f"products/{product_name}/" in file_path:
            continue
        if "/migrations/" in file_path:
            continue
        if ".backend.facade" in import_text:
            continue
        if ".backend.presentation" in import_text:
            continue

        counts[product_name] = counts.get(product_name, 0) + 1

    return counts


def _count_inbound_violations(name: str, inbound_map: dict[str, int] | None = None) -> int | None:
    """Count inbound violations for a single product. None means scan failed."""
    if inbound_map is not None:
        return inbound_map.get(name, 0)
    built = _build_inbound_violation_map()
    if built is None:
        return None
    return built.get(name, 0)


def score_boundaries(name: str, product_dir: Path, inbound_map: dict[str, int] | None = None) -> DimensionScore:
    """Tach interfaces + cross-product import hygiene.

    Points breakdown (100 total):
      tach.toml entry + interfaces:               10
      no cross-product depends_on in tach:         15 (coupling declaration)
      no outbound non-facade imports:              15 (this product's own code)
      no inbound non-facade imports:               60 (the big one — others
        bypassing the facade is the real isolation failure)
    """
    if not _has_python_files(product_dir):
        return DimensionScore("boundaries", 0, "no Python files", applicable=False)

    score = 0
    parts = []

    # Tach entry + interfaces
    module_path = f"products.{name}"
    block = get_tach_block(module_path)

    if block:
        has_inline_interfaces = "interfaces" in block and "interfaces = []" not in block
        has_global_interfaces = False
        if not has_inline_interfaces:
            tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
            has_global_interfaces = bool(
                re.search(
                    rf"\[\[interfaces\]\].*?from\s*=\s*\[.*?{re.escape(name)}",
                    tach_content,
                    re.DOTALL,
                )
            )
        if has_inline_interfaces or has_global_interfaces:
            score += 10
            parts.append("tach + interfaces")
        else:
            score += 5
            parts.append("tach (no interfaces)")

        # Cross-product depends_on: each one is an explicit coupling
        n_cross_deps, _cross_deps = _count_tach_depends_on(block)
        if n_cross_deps == 0:
            score += 15
            parts.append("no cross-product deps")
        else:
            score += max(0, 15 - n_cross_deps * 5)
            parts.append(f"{n_cross_deps} cross-product deps")
    else:
        parts.append("not in tach.toml")

    # Outbound: this product importing other products' internals
    outbound = get_cross_product_internal_imports(product_dir, name)
    if not outbound:
        score += 15
        parts.append("outbound clean")
    else:
        score += max(0, 15 - len(outbound) * 5)
        parts.append(f"{len(outbound)} outbound violations")

    # Inbound: other code importing this product's non-facade internals
    inbound = _count_inbound_violations(name, inbound_map)
    if inbound is None:
        parts.append("inbound scan failed")
    elif inbound == 0:
        score += 60
        parts.append("inbound clean")
    else:
        score += max(0, 60 - inbound * 3)
        parts.append(f"{inbound} inbound violations")

    return DimensionScore("boundaries", score, ", ".join(parts))


# ---------------------------------------------------------------------------
# Dimension 5: Codegen
# ---------------------------------------------------------------------------


def score_codegen(product_dir: Path) -> DimensionScore:
    """Frontend code generation adoption.

    Measures whether the product uses the generated API client instead of
    manual api.* calls. Having generated/api.ts is free (hogli build:openapi
    creates it for everyone) — what matters is actual usage.

    Score = percentage of API calls using generated client:
      100 * generated_used / (generated_used + manual_calls)
    """
    frontend_dir = product_dir / "frontend"
    if not frontend_dir.exists():
        return DimensionScore("codegen", 0, "no frontend", applicable=False)

    metrics = codegen_adoption(frontend_dir)
    available = metrics["generated_available"]
    used = metrics["generated_used"]
    manual = metrics["manual_calls"]

    # No frontend API usage at all — still applicable, just 0
    if available == 0 and manual == 0:
        return DimensionScore("codegen", 0, "no API usage")

    total_calls = used + manual

    if total_calls > 0:
        score = round(100 * used / total_calls)
        detail = f"{score}% codegen ({used} generated, {manual} manual)"
    else:
        score = 0
        detail = "no API usage"

    return DimensionScore("codegen", score, detail)


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------


def score_product(
    name: str,
    *,
    assigned_counts: dict[str, int] | None = None,
    inbound_map: dict[str, int] | None = None,
    product_yamls: dict[str, dict] | None = None,
) -> ProductScore:
    """Compute all dimension scores for a single product."""
    if assigned_counts is None:
        assigned_counts = _load_model_assignments()

    meta = (product_yamls or {}).get(name) or load_product_yaml(name)
    product_dir = PRODUCTS_DIR / name
    backend_dir = product_dir / "backend"

    raw_owners = meta.get("owners", [])
    owners = raw_owners if isinstance(raw_owners, list) and all(isinstance(o, str) for o in raw_owners) else []

    ps = ProductScore(
        product=name,
        display_name=meta.get("name", "") if isinstance(meta.get("name"), str) else "",
        owners=owners,
    )
    ps.dimensions = [
        score_models(name, backend_dir, assigned_counts),
        score_facade(backend_dir),
        score_presentation(backend_dir),
        score_boundaries(name, product_dir, inbound_map),
        score_codegen(product_dir),
    ]
    return ps


def score_all_products() -> list[ProductScore]:
    """Score all products, sorted by overall score descending."""
    product_dirs = sorted(
        d.name
        for d in PRODUCTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_")) and d.name != "__pycache__" and (d / "__init__.py").exists()
    )

    assigned_counts = _load_model_assignments()
    product_yamls = load_all_product_yamls()
    inbound_map = _build_inbound_violation_map()
    if inbound_map is None:
        import warnings

        warnings.warn("inbound violation scan failed (rg unavailable or timeout)", stacklevel=2)
        inbound_map = {}

    scores = [
        score_product(name, assigned_counts=assigned_counts, inbound_map=inbound_map, product_yamls=product_yamls)
        for name in product_dirs
    ]
    scores.sort(key=lambda s: s.overall or -1, reverse=True)
    return scores


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


_DIM_ORDER = ["models", "facade", "presentation", "boundaries", "codegen"]
_DIM_SHORT = {
    "models": "models",
    "facade": "facade",
    "presentation": "presnt",
    "boundaries": "bounds",
    "codegen": "codgen",
}

_BAR_WIDTH = 15
_MINI_WIDTH = 6


def _bar(score: int, width: int = _BAR_WIDTH) -> str:
    filled = round(score * width / 100)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _mini_bar(dim: DimensionScore) -> str:
    """5-char mini bar for heatmap grid. N/A dims show dots."""
    if not dim.applicable:
        return "\u00b7" * _MINI_WIDTH
    filled = round(dim.score * _MINI_WIDTH / 100)
    return "\u2588" * filled + "\u2591" * (_MINI_WIDTH - filled)


def _dim_line(dim: DimensionScore, connector: str = "\u251c\u2500") -> str:
    if not dim.applicable:
        return f"  {connector} {dim.name:14s}    -  ({dim.detail})"
    return f"  {connector} {dim.name:14s}  {dim.score:3d}  {_bar(dim.score)}  {dim.detail}"


def generate_report(scores: list[ProductScore]) -> str:
    """Generate a heatmap grid report for all products."""
    lines: list[str] = []

    lines.append("Product Maturity Report")
    lines.append("")
    lines.append("Dimensions (sequential): models \u2192 facade \u2192 presentation \u2192 boundaries \u2192 codegen")
    lines.append("")

    # Summary
    applicable = [s for s in scores if s.overall is not None]
    if applicable:
        overall_scores = [s.overall for s in applicable if s.overall is not None]
        avg = round(sum(overall_scores) / len(overall_scores))
        high = sum(1 for s in applicable if (s.overall or 0) >= 80)
        mid = sum(1 for s in applicable if 50 <= (s.overall or 0) < 80)
        low = sum(1 for s in applicable if (s.overall or 0) < 50)
        lines.append(f"{len(applicable)} products, avg {avg}/100  ({high} high, {mid} mid, {low} low)")
        lines.append("")

    # Find max product name length for alignment
    scored = [ps for ps in scores if ps.overall is not None]
    max_name = max((len(ps.product) for ps in scored), default=20)
    name_w = max(max_name, 20)

    # Header
    dim_header = "  ".join(f"{_DIM_SHORT[d]:>{_MINI_WIDTH}s}" for d in _DIM_ORDER)
    lines.append(f"{'':>{name_w}s}  score  {dim_header}")
    lines.append("")

    # Rows
    for ps in scored:
        dim_map = ps.dimension_map
        mini_bars = "  ".join(_mini_bar(dim_map[d]) if d in dim_map else "\u00b7" * _MINI_WIDTH for d in _DIM_ORDER)
        lines.append(f"{ps.product:>{name_w}s}  {ps.overall:>3d}    {mini_bars}")

    # Owner rollup
    owner_scores: dict[str, list[int]] = {}
    for ps in scores:
        if ps.overall is not None:
            for owner in ps.owners:
                owner_scores.setdefault(owner, []).append(ps.overall)

    if owner_scores:
        lines.append("")
        lines.append("By Team")
        for owner, vals in sorted(owner_scores.items(), key=lambda t: -sum(t[1]) / len(t[1])):
            avg = round(sum(vals) / len(vals))
            lines.append(f"  {owner:40s}  {avg:3d}  {_bar(avg, 10)}  ({len(vals)} products)")
        lines.append("")

    return "\n".join(lines)


def generate_detail(ps: ProductScore) -> str:
    """Generate detailed single-product maturity breakdown with tree connectors."""
    lines: list[str] = []

    overall = ps.overall
    score_str = "N/A" if overall is None else f"{overall}/100"
    name = ps.display_name or ps.product
    owner_str = f" ({', '.join(ps.owners)})" if ps.owners else ""
    lines.append(f"{name}{owner_str}  {score_str}")
    lines.append("")

    applicable = list(ps.dimensions)
    for i, dim in enumerate(applicable):
        is_last = i == len(applicable) - 1
        connector = "\u2514\u2500" if is_last else "\u251c\u2500"
        lines.append(_dim_line(dim, connector))

    if overall is not None:
        lines.append("")
        lines.append(f"  {'overall':>17s}  {overall:3d}  {_bar(overall)}")

    # Append codegen call-site details if there are manual calls
    frontend_dir = PRODUCTS_DIR / ps.product / "frontend"
    if frontend_dir.exists():
        sites = codegen_call_sites(frontend_dir)
        if sites:
            lines.append("")
            lines.append("  codegen call sites:")
            for site in sites:
                arrow = f"\u2192 {site.generated_equivalent}" if site.generated_equivalent else "(no match)"
                lines.append(f"    {site.file}:{site.line}  {site.verb}  {arrow}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Codegen detail report
# ---------------------------------------------------------------------------


def generate_codegen_report(products: list[str] | None = None) -> str:
    """Generate a detailed codegen adoption report showing call sites and matches.

    If products is None, reports on all products with manual API calls.
    """

    if products is None:
        products = sorted(
            d.name
            for d in PRODUCTS_DIR.iterdir()
            if d.is_dir()
            and not d.name.startswith((".", "_"))
            and d.name != "__pycache__"
            and (d / "__init__.py").exists()
        )

    lines: list[str] = []
    total_manual = 0
    total_matched = 0

    for name in products:
        frontend_dir = PRODUCTS_DIR / name / "frontend"
        if not frontend_dir.exists():
            continue

        sites = codegen_call_sites(frontend_dir)
        if not sites:
            continue

        matched = sum(1 for s in sites if s.generated_equivalent)
        total_manual += len(sites)
        total_matched += matched

        pct = round(100 * matched / len(sites)) if sites else 0
        lines.append(f"{name}  {matched}/{len(sites)} matched ({pct}%)")

        for site in sites:
            arrow = f"→ {site.generated_equivalent}" if site.generated_equivalent else "  (no match)"
            lines.append(f"  {site.file}:{site.line}  {site.verb}({site.url[:50]})  {arrow}")

        lines.append("")

    if total_manual > 0:
        overall_pct = round(100 * total_matched / total_manual)
        header = f"Codegen adoption: {total_matched}/{total_manual} manual calls have generated equivalents ({overall_pct}%)\n"
    else:
        header = "No manual API calls found.\n"

    return header + "\n" + "\n".join(lines)
