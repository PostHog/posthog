"""Dimension 2: facade + contracts + logic separation."""

from __future__ import annotations

from pathlib import Path

from ..ast_helpers import (
    get_frozen_dataclass_names,
    get_model_names,
    get_public_function_names,
    has_any_function_defs,
    imports_any,
    view_facade_usage,
)
from ..paths import find_views_path
from . import common, scores


def score_facade(backend_dir: Path) -> scores.DimensionScore:
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
    has_backend = backend_dir.exists() and common._has_python_files(backend_dir)
    if not has_backend:
        return scores.DimensionScore("facade", 0, "no backend", applicable=False)

    model_names = get_model_names(backend_dir)
    views_path, _ = find_views_path(backend_dir)
    if not model_names and not views_path and not (backend_dir / "facade").exists():
        return scores.DimensionScore("facade", 0, "no models or views", applicable=False)

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
    return scores.DimensionScore("facade", score, ", ".join(parts), next_steps=next_steps, skills=skills)
