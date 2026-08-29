"""Dimension 3: views through facade, serializers on contracts."""

from __future__ import annotations

import re
from pathlib import Path

from ..ast_helpers import (
    find_direct_orm_queries,
    get_model_names,
    get_orm_bound_serializer_names,
    has_any_function_defs,
    view_facade_usage,
)
from ..isolation import presentation_bypass_entries
from ..paths import find_views_path
from . import common, scores


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

    def product(side: str) -> str:
        m = re.match(r"products\.([^.]+)\.", side.strip())
        return m.group(1) if m else ""

    # a cross-product edge (routes registering another product's view) keeps its full path,
    # otherwise the product name would be the one detail the line loses
    if product(sides[0]) != product(sides[1]):
        return f"{strip(sides[0])} → {sides[1].strip()}"
    return f"{strip(sides[0])} → backend.{strip(sides[1])}"


def score_presentation(name: str, backend_dir: Path, pyproject_text: str | None = None) -> scores.DimensionScore:
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
            return scores.DimensionScore("presentation", 0, "no views", applicable=False)
        return scores.DimensionScore(
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
        evidence.append(("ORM call sites", common._cap(orm_locations, 25)))

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

    return scores.DimensionScore(
        "presentation", score, ", ".join(parts), next_steps=next_steps, skills=skills, evidence=evidence
    )
