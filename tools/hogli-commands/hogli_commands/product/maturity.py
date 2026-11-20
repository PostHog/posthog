"""Product maturity scoring and report generation.

Scores each product across two actionable dimensions:

  1. Models     — move models into products/
  2. Codegen    — schema annotations, generated TS client adoption

The boundaries between products are hoglint's: `hoglint check` reports them.

Run from repo root:
    bin/hogli product:maturity          # single product detail
    bin/hogli product:maturity --all    # ranked report of all products
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from .ast_helpers import get_model_names
from .paths import PRODUCTS_DIR
from .product_yaml import load_all_product_yamls, load_product_yaml
from .ts_helpers import ManualCallSite, codegen_adoption, codegen_call_sites

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
    # Agent-actionable steps to raise the score. Only populated when score < 100.
    # Each entry is a single sentence the agent can act on directly.
    next_steps: list[str] = field(default_factory=list)
    # Skill slash commands to invoke (e.g. "/adopting-generated-api-types")
    # before attempting the work.
    skills: list[str] = field(default_factory=list)
    # Structured findings the scorer surfaced — list of (label, items) sections.
    # Items are pre-formatted strings, one per call site. Rendered uniformly between to-fix
    # and skills.
    evidence: list[tuple[str, list[str]]] = field(default_factory=list)


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

    next_steps: list[str] = []
    skills: list[str] = []
    if still_to_move > 0:
        next_steps.append(
            f"STOP — do not attempt this move yourself. {still_to_move} model(s) still live in "
            f"posthog/models/ (or ee/models/) and need to be relocated into "
            f"products/{name}/backend/models/. Model moves require a SeparateDatabaseAndState "
            f"migration coordinated with team devex; doing it ad-hoc breaks production. Open a "
            f"request with team devex (#team-devex on Slack) referencing this product and ask "
            f"them to schedule the migration."
        )
        next_steps.append(
            "Once devex has scheduled and merged the move, the product's boundary work becomes "
            "actionable: `hoglint check` lists it, and you can tackle it yourself."
        )

    return DimensionScore("models", pct, detail, next_steps=next_steps, skills=skills)


# ---------------------------------------------------------------------------
# Dimension 2: Codegen
# ---------------------------------------------------------------------------


def _call_site_target(site: ManualCallSite) -> str:
    """What to migrate a manual call site to, for the evidence line."""
    if site.generated_equivalent:
        return f"→ {site.generated_equivalent}"
    if site.note:
        return f"({site.note})"
    if site.namespaced:
        return "→ this product's generated client"
    return "(no match)"


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

    next_steps: list[str] = []
    skills: list[str] = []
    evidence: list[tuple[str, list[str]]] = []
    if score < 100 and manual > 0:
        next_steps.append(
            f"Replace the {manual} manual `api.*`/`api.<entity>.<verb>` call(s) listed below "
            f"with the generated client (each one shows the matching generated function)."
        )
        next_steps.append(
            "For sites marked `(no match)`, the backend viewset is missing schema annotations "
            "(`@validated_request` or `@extend_schema`) or the serializer field types are too "
            "loose. Fix the backend, run `hogli build:openapi`, then migrate the call."
        )
        sites = codegen_call_sites(frontend_dir)
        if sites:
            items = [f"{site.file}:{site.line}  {site.verb}  {_call_site_target(site)}" for site in sites]
            evidence.append(("call sites", items))
        skills.append("/adopting-generated-api-types")
        skills.append("/improving-drf-endpoints")
    elif score < 100 and total_calls > 0:
        next_steps.append(
            "All API calls are accounted for but none use the generated client. Run "
            "`hogli build:openapi` and migrate to the generated functions in "
            "products/<name>/frontend/generated/api.ts."
        )
        skills.append("/adopting-generated-api-types")

    return DimensionScore("codegen", score, detail, next_steps=next_steps, skills=skills, evidence=evidence)


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------


def score_product(
    name: str,
    *,
    assigned_counts: dict[str, int] | None = None,
    product_yamls: dict[str, dict] | None = None,
) -> ProductScore:
    """Compute all dimension scores for a single product.

    The --all caller reads the model assignments and the product.yaml files once and threads them
    in; a single-product run leaves them None and reads on demand.
    """
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
    scores = [
        score_product(name, assigned_counts=assigned_counts, product_yamls=product_yamls) for name in product_dirs
    ]
    scores.sort(key=lambda s: s.overall or -1, reverse=True)
    return scores


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


_DIM_ORDER = ["models", "codegen"]
_DIM_SHORT = {
    "models": "models",
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
    lines.append("Dimensions: models, codegen")
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
    """Generate detailed single-product maturity breakdown with tree connectors.

    Each dimension that scored below 100 is followed by a "to fix" block listing
    concrete agent-actionable steps, an "evidence" section with structured
    findings (call sites, violations, etc.), and the skills to invoke.
    """
    lines: list[str] = []

    overall = ps.overall
    score_str = "N/A" if overall is None else f"{overall}/100"
    name = ps.display_name or ps.product
    owner_str = f" ({', '.join(ps.owners)})" if ps.owners else ""
    lines.append(f"{name}{owner_str}  {score_str}")
    lines.append("")

    applicable = list(ps.dimensions)
    target_line_width = 100
    for i, dim in enumerate(applicable):
        is_last = i == len(applicable) - 1
        connector = "\u2514\u2500" if is_last else "\u251c\u2500"
        lines.append(_dim_line(dim, connector))

        has_body = bool(dim.next_steps or dim.skills or dim.evidence)
        if not has_body:
            if not is_last:
                lines.append(f"  \u2502")
            continue

        # Indent guide matches the tree above. Use a vertical bar for non-last
        # dimensions so the tree stays visually intact, spaces for the last.
        guide = "\u2502" if not is_last else " "
        gutter = f"  {guide}     "  # column under "\u251c\u2500 <name>"
        bullet_indent = f"{gutter}  "
        cont_indent = f"{gutter}    "
        # Wrap so the rendered line (gutter + bullet + text) stays under target.
        wrap_width = max(40, target_line_width - len(cont_indent))

        blank = f"  {guide}"
        sections_emitted = 0

        # Blank line under the score, then the body
        lines.append(blank)

        if dim.next_steps:
            lines.append(f"{gutter}to fix:")
            for j, step in enumerate(dim.next_steps):
                wrapped = textwrap.wrap(step, width=wrap_width) or [step]
                lines.append(f"{bullet_indent}\u2022 {wrapped[0]}")
                for cont in wrapped[1:]:
                    lines.append(f"{cont_indent}{cont}")
                if j < len(dim.next_steps) - 1:
                    lines.append(blank)
            sections_emitted += 1

        for label, items in dim.evidence:
            if not items:
                continue
            if sections_emitted:
                lines.append(blank)
            lines.append(f"{gutter}{label}:")
            for item in items:
                lines.append(f"{bullet_indent}{item}")
            sections_emitted += 1

        if dim.skills:
            if sections_emitted:
                lines.append(blank)
            skills_str = "  ".join(dim.skills)
            lines.append(f"{gutter}skills: {skills_str}")

        if not is_last:
            lines.append(blank)

    if overall is not None:
        lines.append("")
        lines.append(f"  {'overall':>17s}  {overall:3d}  {_bar(overall)}")

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

        matched = sum(1 for s in sites if s.generated_equivalent or s.namespaced)
        total_manual += len(sites)
        total_matched += matched

        pct = round(100 * matched / len(sites)) if sites else 0
        lines.append(f"{name}  {matched}/{len(sites)} matched ({pct}%)")

        for site in sites:
            lines.append(f"  {site.file}:{site.line}  {site.verb}({site.url[:50]})  {_call_site_target(site)}")

        lines.append("")

    if total_manual > 0:
        overall_pct = round(100 * total_matched / total_manual)
        header = f"Codegen adoption: {total_matched}/{total_manual} manual calls have generated equivalents ({overall_pct}%)\n"
    else:
        header = "No manual API calls found.\n"

    return header + "\n" + "\n".join(lines)
