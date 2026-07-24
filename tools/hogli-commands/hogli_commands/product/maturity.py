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
import textwrap
import warnings
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .ast_helpers import (
    find_direct_orm_queries,
    get_frozen_dataclass_names,
    get_model_names,
    get_orm_bound_serializer_names,
    get_public_function_names,
    has_any_function_defs,
    imports_any,
    view_facade_usage,
)
from .isolation import (
    IsolationStatus,
    compute_isolation_status,
    has_legacy_interface_leaks,
    has_tach_interface,
    presentation_bypass_entries,
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
    # Agent-actionable steps to raise the score. Only populated when score < 100.
    # Each entry is a single sentence the agent can act on directly.
    next_steps: list[str] = field(default_factory=list)
    # Skill slash commands to invoke (e.g. "/isolating-product-facade-contracts")
    # before attempting the work.
    skills: list[str] = field(default_factory=list)
    # Structured findings the scorer surfaced — list of (label, items) sections.
    # Items are pre-formatted strings (e.g. "presentation/views.py:42",
    # "products.foo.backend.models"). Rendered uniformly between to-fix and skills.
    evidence: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class ProductScore:
    product: str
    display_name: str = ""
    owners: list[str] = field(default_factory=list)
    dimensions: list[DimensionScore] = field(default_factory=list)
    # External-vs-internal seal synthesis. None for products with no backend.
    isolation: IsolationStatus | None = None

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


def _cap(items: list[str], limit: int) -> list[str]:
    """Truncate a list, appending an ellipsis row when items were dropped."""
    if len(items) <= limit:
        return items
    return [*items[:limit], f"… and {len(items) - limit} more"]


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
            "Once devex has scheduled and merged the move, the rest of the maturity dimensions "
            "(facade, presentation, boundaries) become actionable and you can tackle them yourself."
        )

    return DimensionScore("models", pct, detail, next_steps=next_steps, skills=skills)


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
    next_steps: list[str] = []

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
            next_steps.append(
                "Make backend/facade/contracts.py pure: remove all `django` and `rest_framework` "
                "imports. Contracts must be plain frozen dataclasses so they can be consumed across "
                "product boundaries without dragging in DRF or the ORM."
            )
        else:
            parts.append("contracts (empty)")
            next_steps.append(
                "backend/facade/contracts.py exists but defines no frozen dataclasses. Add "
                "`@dataclass(frozen=True)` types describing every value the facade returns "
                "(see products/visual_review/backend/facade/contracts.py)."
            )
    else:
        parts.append("no contracts")
        next_steps.append(
            "Create backend/facade/contracts.py with frozen dataclasses that describe each "
            "facade return value. No Django, no DRF — just stdlib types. This is the public "
            "contract other products read against."
        )

    # Facade — must have actual function definitions, not just re-exports
    facade_path = backend_dir / "facade" / "api.py"
    real_facade = False
    if facade_path.exists():
        real_facade = has_any_function_defs(facade_path)
        if not real_facade:
            parts.append("facade (re-export only)")
            next_steps.append(
                "backend/facade/api.py only re-exports; it doesn't define any functions. Move "
                "logic into real `def` entrypoints (`list_*`, `get_*`, `create_*`, `update_*`, "
                "`delete_*`) that map ORM rows to contract dataclasses before returning."
            )
        else:
            impure = imports_any(facade_path, ["rest_framework"])
            fn_names = get_public_function_names(facade_path)
            if not impure:
                score += 15
            else:
                score += 5
                parts.append("facade (impure)")
                next_steps.append(
                    "Remove `rest_framework` imports from backend/facade/api.py. The facade must "
                    "return contract dataclasses; serializing to DRF Response belongs in "
                    "presentation/views.py."
                )

            if len(fn_names) >= 3:
                score += 15
                parts.append(f"facade ({len(fn_names)} methods)")
            elif fn_names:
                score += 5
                parts.append(f"facade (stub, {len(fn_names)} method)")
                next_steps.append(
                    f"Facade is a stub ({len(fn_names)} method). Add a method per capability the "
                    "product exposes — list, retrieve, create, update, delete, plus any async "
                    "task entrypoints. Each viewset action and Celery task should call exactly one."
                )
    else:
        parts.append("no facade")
        next_steps.append(
            "Create backend/facade/api.py with public functions wrapping logic. Use "
            "products/visual_review/backend/facade/api.py as the reference shape."
        )

    # Logic
    has_logic = (backend_dir / "logic.py").exists() or (backend_dir / "logic").is_dir()
    if has_logic:
        score += 15
        parts.append("logic")
    else:
        parts.append("no logic")
        next_steps.append(
            "Add backend/logic.py (or a logic/ package) that owns business rules and ORM access. "
            "The facade should be a thin orchestration layer that calls into logic."
        )

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
            next_steps.append(
                "Views import the facade but the facade is just a re-export shim. Fix the facade "
                "first (above), then this lights up automatically."
            )
        else:
            parts.append("views skip facade")
            next_steps.append(
                "Refactor views to call facade functions instead of importing models, querysets, "
                "or logic directly. Each view action should be one facade call plus a serializer."
            )
    else:
        parts.append("views not in product")
        next_steps.append(
            "Move the product's views into products/<name>/backend/presentation/views.py. The "
            "facade has no leverage if the views still live in posthog/api/ or ee/api/."
        )

    skills = ["/isolating-product-facade-contracts"] if next_steps else []
    return DimensionScore("facade", score, ", ".join(parts), next_steps=next_steps, skills=skills)


# ---------------------------------------------------------------------------
# Dimension 3: Presentation
# ---------------------------------------------------------------------------


def _format_bypass(entry: str) -> str:
    """Make an import-linter ignore_imports entry readable as a per-view worklist item.

    "products.x.backend.presentation.views.external -> products.x.backend.models"
    becomes "presentation.views.external → backend.models".
    """
    sides = entry.split(" -> ")
    if len(sides) != 2:
        return entry

    def strip(side: str) -> str:
        m = re.match(r"products\.[^.]+\.backend\.(.+)", side.strip())
        return m.group(1) if m else side.strip()

    return f"{strip(sides[0])} → backend.{strip(sides[1])}"


def score_presentation(name: str, backend_dir: Path, pyproject_text: str | None = None) -> DimensionScore:
    """Views through facade, serializers on contracts.

    Points breakdown (100 total):
      views at correct location (presentation/):  25
      views use facade:                           25
      no direct ORM in views:                     25
      serializers not ORM-bound:                  25

    The "views use facade" 25 is decided by import-linter ground truth when the
    product is isolated: any open presentation-wave bypass means presentation still
    reaches internals directly, so the points are withheld regardless of what the
    AST heuristic sees. The deferral list doubles as the per-view worklist.
    """
    views_path, correct_location = find_views_path(backend_dir)

    if views_path is None:
        model_names = get_model_names(backend_dir)
        if not model_names:
            return DimensionScore("presentation", 0, "no views", applicable=False)
        return DimensionScore(
            "presentation",
            0,
            "views not in product",
            next_steps=[
                "Move the product's views into products/<name>/backend/presentation/views.py "
                "(URL routing stays unchanged; just relocate the module).",
            ],
            skills=["/isolating-product-facade-contracts", "/improving-drf-endpoints"],
        )

    score = 0
    parts = []
    next_steps: list[str] = []
    evidence: list[tuple[str, list[str]]] = []

    if correct_location:
        score += 25
        parts.append("correct location")
    else:
        parts.append(f"at {views_path.relative_to(backend_dir)}")
        next_steps.append(
            f"Views currently at {views_path.relative_to(backend_dir)}. Move them to "
            f"backend/presentation/views.py — that's the canonical location the architecture "
            f"and tach interfaces expect."
        )

    uses_facade, _ = view_facade_usage(views_path)
    orm_locations = find_direct_orm_queries(views_path)
    orm_queries = len(orm_locations)

    # Check if the facade is real (has function definitions, not re-exports)
    facade_api = backend_dir / "facade" / "api.py"
    real_facade = facade_api.exists() and has_any_function_defs(facade_api)

    # Ground truth wins over the AST heuristic: each open import-linter deferral is a
    # view that still bypasses the facade, so the product is not internally sealed.
    bypass_entries = presentation_bypass_entries(name, pyproject_text)

    if bypass_entries:
        parts.append(f"{len(bypass_entries)} facade bypass(es)")
        next_steps.append(
            "Presentation still reaches internals directly. Thin each view below to "
            "parse → facade → serialize, then delete its line from the import-linter "
            "ignore_imports TODO section in pyproject.toml — that empties the internal seal."
        )
        evidence.append(("facade bypasses (import-linter deferrals)", [_format_bypass(e) for e in bypass_entries]))
    elif uses_facade and real_facade:
        score += 25
        parts.append("uses facade")
    elif uses_facade:
        parts.append("imports facade (but facade is fake)")
        next_steps.append(
            "Views import the facade but it's a re-export shim. Land a real facade with `def` "
            "functions returning contracts before this dimension can score."
        )
    else:
        parts.append("no facade usage")
        next_steps.append(
            "Replace direct model/logic imports in views with calls to backend.facade.api. Each "
            "viewset action should fetch contracts via the facade and hand them to a serializer."
        )

    if orm_queries == 0:
        score += 25
        parts.append("no direct ORM")
    else:
        parts.append(f"{orm_queries} .objects calls")
        next_steps.append(
            f"Remove the {orm_queries} direct `.objects` query/queries listed below. Push them "
            f"down into facade/logic and return contract dataclasses instead — presentation "
            f"should never hit the ORM."
        )
        evidence.append(("ORM call sites", _cap(orm_locations, 25)))

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
            next_steps.append(
                f"Convert the {len(orm_bound)} ModelSerializer(s) listed below to plain "
                f"`Serializer` subclasses backed by contract dataclasses. ModelSerializer leaks "
                f"the ORM through the presentation boundary and produces weak OpenAPI types."
            )
            evidence.append(("ORM-bound serializers", orm_bound))
    else:
        score += 25
        parts.append("no serializers (ok)")

    skills: list[str] = []
    if next_steps:
        skills.append("/isolating-product-facade-contracts")
        skills.append("/improving-drf-endpoints")

    return DimensionScore(
        "presentation", score, ", ".join(parts), next_steps=next_steps, skills=skills, evidence=evidence
    )


# ---------------------------------------------------------------------------
# Dimension 4: Boundaries
# ---------------------------------------------------------------------------


def _build_cross_import_maps() -> tuple[dict[str, list[str]], dict[str, list[str]]] | None:
    """One rg pass over the repo, distributed into inbound and outbound maps.

    Both halves care about the same thing — `import products.<x>.backend.<…>` lines —
    so they share a single scan instead of re-walking every product's files per product.

      inbound[target]  = external code (core or another product) importing that product's
                         non-facade internals — the real isolation failure.
      outbound[source] = that product's own files importing ANOTHER product's internals.

    Each value is a list of `relpath:line  module` strings for evidence. Returns None if
    rg is unavailable or times out.
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

    inbound: dict[str, list[str]] = {}
    outbound: dict[str, list[str]] = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # rg -n format: <path>:<line>:<text>
        colon_idx = line.find(":", 1)
        if colon_idx == -1:
            continue
        colon2_idx = line.find(":", colon_idx + 1)
        if colon2_idx == -1:
            continue
        file_path = line[:colon_idx]
        line_num = line[colon_idx + 1 : colon2_idx]
        import_text = line[colon2_idx + 1 :].strip()

        # Which product is being imported? (handles both from/import style)
        match = re.search(r"products\.(\w+)\.backend\.\w+", import_text)
        if not match:
            continue
        imported = match.group(1)
        module = match.group(0)

        try:
            rel_path = str(Path(file_path).relative_to(REPO_ROOT))
        except ValueError:
            rel_path = file_path
        evidence = f"{rel_path}:{line_num}  {module}"

        # Which product owns the importing file? Empty when it lives in core (ee/, posthog/).
        src = re.match(r"products/(\w+)/", rel_path)
        source = src.group(1) if src else ""

        is_facade = ".backend.facade" in import_text
        is_presentation = ".backend.presentation" in import_text

        # inbound: someone outside `imported` reaching past its facade/presentation surface.
        # Django admin's project-wide registry must import each product's admin classes and
        # the models they reference — there's no facade equivalent for `admin.site.register`.
        in_admin = "/posthog/admin/" in file_path or rel_path.startswith("posthog/admin/")
        if (
            source != imported
            and not is_facade
            and not is_presentation
            and "/migrations/" not in file_path
            and not in_admin
        ):
            inbound.setdefault(imported, []).append(evidence)

        # outbound: `source` reaching into another product's non-facade internals.
        if source and source != imported and not is_facade:
            outbound.setdefault(source, []).append(evidence)

    return inbound, outbound


def score_boundaries(
    name: str,
    product_dir: Path,
    inbound_map: dict[str, list[str]] | None = None,
    outbound_map: dict[str, list[str]] | None = None,
    tach_content: str | None = None,
) -> DimensionScore:
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

    content = tach_content if tach_content is not None else (TACH_TOML.read_text() if TACH_TOML.exists() else "")

    score = 0
    parts = []
    next_steps: list[str] = []
    evidence: list[tuple[str, list[str]]] = []

    # Tach entry + interfaces
    module_path = f"products.{name}"
    block = get_tach_block(module_path)

    if block:
        if has_tach_interface(name, content):
            score += 10
            parts.append("tach + interfaces")
        else:
            score += 5
            parts.append("tach (no interfaces)")
            next_steps.append(
                f'Add `interfaces = ["products.{name}.backend.facade.*", '
                f'"products.{name}.backend.presentation.*"]` to the [[modules]] entry in '
                f"tach.toml so tach enforces what's public."
            )

        # Cross-product depends_on: each one is an explicit coupling
        n_cross_deps, cross_deps = _count_tach_depends_on(block)
        if n_cross_deps == 0:
            score += 15
            parts.append("no cross-product deps")
        else:
            score += max(0, 15 - n_cross_deps * 5)
            parts.append(f"{n_cross_deps} cross-product deps")
            next_steps.append(
                f"Drop the {n_cross_deps} cross-product depends_on entry/entries from tach.toml "
                f"(listed below). If a real dependency exists, route through that product's "
                f"facade so the coupling is interface-level rather than module-level."
            )
            evidence.append(("tach depends_on", list(cross_deps)))
    else:
        parts.append("not in tach.toml")
        next_steps.append(
            f"Add a [[modules]] entry for products.{name} to tach.toml with explicit "
            f"`depends_on` and `interfaces`. Without it, tach won't catch boundary regressions."
        )

    # Outbound: this product importing other products' internals
    outbound = outbound_map.get(name, []) if outbound_map is not None else None
    if outbound is None:
        parts.append("outbound scan failed")
        next_steps.append(
            "Outbound scan failed — `rg` is missing or timed out. Install ripgrep and re-run "
            "`hogli product:maturity` for an accurate outbound count."
        )
    elif not outbound:
        score += 15
        parts.append("outbound clean")
    else:
        score += max(0, 15 - len(outbound) * 5)
        parts.append(f"{len(outbound)} outbound violations")
        next_steps.append(
            f"Replace the {len(outbound)} outbound import(s) of other products' internals listed "
            f"below with calls to those products' facades."
        )
        evidence.append(("outbound violations", _cap(outbound, 25)))

    # Inbound: other code importing this product's non-facade internals
    inbound = inbound_map.get(name, []) if inbound_map is not None else None
    if inbound is None:
        parts.append("inbound scan failed")
        next_steps.append(
            "Inbound scan failed — `rg` is missing or timed out. Install ripgrep and re-run "
            "`hogli product:maturity` for an accurate inbound count."
        )
    elif not inbound:
        score += 60
        parts.append("inbound clean")
    else:
        score += max(0, 60 - len(inbound) * 3)
        parts.append(f"{len(inbound)} inbound violations")
        next_steps.append(
            f"Audit the {len(inbound)} external import(s) of this product's internals listed "
            f"below. Each one either belongs in the facade's public surface (then expose it "
            f"through facade.api) or should not exist (refactor the caller). Update tach "
            f"`interfaces` to match."
        )
        # Cap evidence so the report doesn't explode for products with hundreds of violations
        evidence.append(("inbound violations", _cap(inbound, 25)))

    # A declared legacy-leak interface (e.g. backend.admin exposed to core) is an external
    # bypass the inbound scan deliberately exempts. Without docking it here, a leaky product
    # still scores a near-perfect boundary while the seal capstone says the boundary is open.
    if has_legacy_interface_leaks(content, module_path):
        score -= min(score, 30)
        parts.append("legacy interface leak")
        next_steps.append(
            "A dedicated legacy-leak [[interfaces]] block exposes non-facade internals to core "
            "(e.g. backend.admin). The external boundary stays open until that coupling is removed "
            "or accepted as permanent; contract-check stays off either way."
        )
        evidence.append(("legacy interface leak", [f"{module_path}: non-facade surface exposed to core in tach.toml"]))

    skills = ["/isolating-product-facade-contracts"] if next_steps else []
    return DimensionScore(
        "boundaries", score, ", ".join(parts), next_steps=next_steps, skills=skills, evidence=evidence
    )


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
            items = [
                f"{site.file}:{site.line}  {site.verb}  "
                + (f"→ {site.generated_equivalent}" if site.generated_equivalent else "(no match)")
                for site in sites
            ]
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
    inbound_map: dict[str, list[str]] | None = None,
    outbound_map: dict[str, list[str]] | None = None,
    maps_resolved: bool = False,
    tach_content: str | None = None,
    pyproject_text: str | None = None,
    product_yamls: dict[str, dict] | None = None,
) -> ProductScore:
    """Compute all dimension scores for a single product.

    `tach_content`/`pyproject_text` let the --all caller read those repo files once and
    thread them in; a single-product run leaves them None and the helpers read on demand.

    The --all caller scans cross-product imports once and passes the maps with
    `maps_resolved=True` (a map may be None, meaning the scan failed — boundaries scoring
    then shows "scan failed" rather than awarding clean points). A single-product run
    leaves it False, so the scan runs once here.
    """
    if assigned_counts is None:
        assigned_counts = _load_model_assignments()

    if not maps_resolved:
        built = _build_cross_import_maps()
        inbound_map, outbound_map = built if built is not None else (None, None)

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
        score_presentation(name, backend_dir, pyproject_text),
        score_boundaries(name, product_dir, inbound_map, outbound_map, tach_content),
        score_codegen(product_dir),
    ]
    if backend_dir.exists():
        ps.isolation = compute_isolation_status(
            name, product_dir, backend_dir, tach_content=tach_content, pyproject_text=pyproject_text
        )
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
    # Read the two repo-level files once and thread them through, instead of letting each
    # of the ~65 products re-read and re-parse them inside the per-product scorers.
    tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    pyproject_text = pyproject_path.read_text() if pyproject_path.exists() else ""
    maps = _build_cross_import_maps()
    if maps is None:
        warnings.warn("cross-product import scan failed (rg unavailable or timeout)", stacklevel=2)
    # On failure both maps stay None, so boundaries scoring reports "scan failed" instead of
    # awarding clean points — and the scan is not re-run per product.
    inbound_map, outbound_map = maps if maps is not None else (None, None)

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


def _isolated_tests_state(status: IsolationStatus) -> tuple[str, str]:
    """(state, reason) for the isolated-tests certificate \u2014 the contract-check skip."""
    if status.isolated_tests_enabled:
        return "ON", "contract-check skip live \u2014 Django suite stays off unrelated CI shards"
    # Eligibility deliberately excludes the tach interface (see IsolationStatus), but the skip
    # is unsound without the external boundary, so READY also requires it.
    if status.eligible_for_isolated_tests and status.externally_sealed:
        missing = []
        if not status.has_contract_check_script:
            missing.append("add backend:contract-check")
        if not status.has_narrowed_turbo:
            missing.append("narrow turbo.json inputs")
        return "READY", f"{' + '.join(missing)} to turn the skip on"
    blockers: list[str] = []
    if not status.is_isolated:
        blockers.append("add a facade (contracts.py + api.py)")
    elif not status.has_real_facade:
        blockers.append("make facade/api.py real (define functions, not re-exports)")
    if status.has_legacy_leaks:
        blockers.append("remove the legacy interface leak block from tach.toml")
    if status.deferred_count > 0:
        blockers.append(f"empty the {status.deferred_count} presentation bypass(es)")
    if not status.has_tach_interface:
        blockers.append("add the tach [[interfaces]] block")
    return "OFF", "; ".join(blockers) if blockers else "prerequisites incomplete"


def _isolation_capstone(status: IsolationStatus) -> list[str]:
    """Render the external-vs-internal seal synthesis: the headline an agent acts on.

    Maps the two seals onto the isolated-tests certificate. The boundary protects
    external consumers (tach); the seal stops the product's own presentation bypassing
    its facade (import-linter). Both done + a real facade earns the contract-check skip.
    """
    if status.externally_sealed:
        ext_state, ext_detail = "sealed", "tach [[interfaces]] on, no legacy leaks"
    elif not status.has_tach_interface:
        ext_state, ext_detail = "open", "no tach [[interfaces]] block \u2014 external code can reach internals"
    else:
        ext_state, ext_detail = "open", "legacy interface leak block present \u2014 core still imports internals"

    if not status.is_isolated:
        int_state, int_detail = "n/a", "no facade yet \u2014 product not isolated"
    elif status.internally_sealed:
        int_state, int_detail = "sealed", "presentation reaches internals only through the facade"
    else:
        int_state, int_detail = (
            f"{status.deferred_count} open",
            "presentation still reaches internals directly (see presentation dimension)",
        )

    tests_state, tests_detail = _isolated_tests_state(status)

    rows = [
        ("external boundary", ext_state, ext_detail),
        ("internal seal", int_state, int_detail),
        ("isolated tests", tests_state, tests_detail),
    ]
    lines = ["  isolation seal"]
    for label, state, detail in rows:
        lines.append(f"    {label:18s}  {state:10s}  {detail}")
    return lines


SEAL_LEGEND = "seal: on=tests live  ready=eligible, not wired  int:N=N internal bypasses open  ext\u2717=external boundary open  \u2014=not isolated"


def _seal_token(status: IsolationStatus | None) -> str:
    """Compact seal state for the --all grid. Each token names the remaining blocker."""
    if status is None or not status.is_isolated:
        return "\u2014"
    if status.isolated_tests_enabled:
        return "on"
    if not status.externally_sealed:
        return "ext\u2717"
    if status.deferred_count > 0:
        # externally sealed but internally unsealed \u2014 looks done, isn't
        return f"int:{status.deferred_count}"
    if status.eligible_for_isolated_tests:
        return "ready"
    return "partial"


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
    lines.append(SEAL_LEGEND)
    lines.append("")
    dim_header = "  ".join(f"{_DIM_SHORT[d]:>{_MINI_WIDTH}s}" for d in _DIM_ORDER)
    lines.append(f"{'':>{name_w}s}  score  {dim_header}  seal")
    lines.append("")

    # Rows
    for ps in scored:
        dim_map = ps.dimension_map
        mini_bars = "  ".join(_mini_bar(dim_map[d]) if d in dim_map else "\u00b7" * _MINI_WIDTH for d in _DIM_ORDER)
        lines.append(f"{ps.product:>{name_w}s}  {ps.overall:>3d}    {mini_bars}  {_seal_token(ps.isolation)}")

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

    if ps.isolation is not None:
        lines.extend(_isolation_capstone(ps.isolation))
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
